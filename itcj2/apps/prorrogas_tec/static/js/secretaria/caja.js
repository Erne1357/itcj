// Prórrogas · Caja (vista de la cajera): busca al alumno o elige de la lista "Por cobrar".
// APIs: /api/prorrogas/v2/caja/*. Todo texto del servidor entra con textContent (nunca innerHTML).
(function () {
  "use strict";

  const root = document.querySelector(".caj");
  if (!root) return;
  const API = root.dataset.api;
  const CAJA = "/caja";
  const $ = (id) => document.getElementById(id);
  const MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];
  const SITUACION = {
    sin_plan: ["Sin plan", "gris"], al_corriente: ["Al corriente", "azul"],
    atrasada: ["Con adeudo", "naranja"], liquidada: ["Liquidada", "vino"],
  };

  const st = { q: "", semestre: "", filtro: "todos", orden: "urgente", page: 1, openId: null };
  let listSeq = 0;
  let searchTimer = null;

  function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  async function api(path, opts) {
    const o = Object.assign({ credentials: "include" }, opts);
    if (o.body !== undefined) { o.method = "POST"; o.headers = { "Content-Type": "application/json" }; o.body = JSON.stringify(o.body); }
    let r;
    try { r = await fetch(API + path, o); } catch (e) { return { ok: false, status: 0, data: { message: "Sin conexión con el servidor." } }; }
    const data = await r.json().catch(() => ({}));
    if (r.status === 403 && !data.message) data.message = "No tienes permiso para esta acción.";
    return { ok: r.ok, status: r.status, data };
  }

  function show(node, msg) { node.textContent = msg || ""; node.hidden = !msg; }

  // Las fechas ISO se leen por partes: new Date("2026-03-01") sería UTC y mostraría el día anterior.
  function fmtDate(iso) {
    if (!iso) return "—";
    const [y, m, d] = String(iso).slice(0, 10).split("-").map(Number);
    return `${d} ${MESES[m - 1]} ${y}`;
  }

  const cents = (v) => Math.round(parseFloat(v) * 100);
  const money = (c) => (isNaN(c) ? "—" : "$" + (c / 100).toLocaleString("es-MX", { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
  const pesos = (s) => money(cents(s));

  async function loadSemestres() {
    const r = await api(CAJA + "/semestres");
    if (!r.ok) { show($("cajError"), r.data.message || "No se pudieron cargar los semestres."); return; }
    (r.data.items || []).forEach((p) => { const o = el("option", null, p.label); o.value = p.id; $("cajSem").append(o); });
  }

  async function loadList() {
    const seq = ++listSeq;
    const qs = new URLSearchParams({ filtro: st.filtro, orden: st.orden, page: st.page });
    if (st.q) qs.set("q", st.q);
    if (st.semestre) qs.set("semestre", st.semestre);
    const r = await api(CAJA + "?" + qs);
    if (seq !== listSeq) return;
    if (!r.ok) {
      show($("cajError"), r.data.message || "No se pudo cargar la lista.");
      ["cajRes", "cajNone", "cajVacio", "cajListHead"].forEach((id) => { $(id).hidden = true; });
      return;
    }
    show($("cajError"), "");
    renderList(r.data);
  }

  function renderList(d) {
    st.page = d.page;
    const buscando = !!st.q;
    $("cajListHead").hidden = buscando;
    $("cajPags").hidden = true;
    $("cajResN").hidden = !buscando;
    const filas = $("cajFilas");
    filas.textContent = "";
    d.items.forEach((e) => filas.append(rowFor(e)));
    const vacio = d.items.length === 0;
    $("cajRes").hidden = vacio;
    $("cajNone").hidden = !(buscando && vacio);
    $("cajVacio").hidden = !(!buscando && vacio);

    if (buscando) {
      const n = d.total;
      $("cajResN").textContent = n > d.items.length ? `${d.items.length} de ${n} resultados`
        : n === 1 ? "1 resultado" : `${n} resultados`;
      return;
    }
    const c = d.conteos || {};
    const todos = c.todos ?? 0;
    $("cajCuenta").textContent = `${todos} ${todos === 1 ? "alumno" : "alumnos"} con pagos pendientes`;
    document.querySelectorAll("#cajFiltros button").forEach((b) => {
      b.setAttribute("aria-selected", String(b.dataset.f === st.filtro));
      b.querySelector("b").textContent = c[b.dataset.f] ?? 0;
    });
    renderPags(d);
  }

  function renderPags(d) {
    const pages = Math.max(1, Math.ceil(d.total / d.per_page));
    $("cajPags").hidden = pages <= 1;
    if (pages <= 1) return;
    const desde = (d.page - 1) * d.per_page + 1;
    $("cajRango").textContent = `${desde}–${desde + d.items.length - 1} de ${d.total}`;
    $("cajPrev").disabled = d.page <= 1;
    $("cajNext").disabled = d.page >= pages;
    const nums = $("cajNums");
    nums.textContent = "";
    for (let n = Math.max(1, d.page - 3); n <= Math.min(pages, d.page + 3); n++) {
      const b = el("button", n === d.page ? "is-cur" : "", String(n));
      b.type = "button";
      if (n === d.page) b.setAttribute("aria-current", "page");
      b.addEventListener("click", () => { st.page = n; loadList(); });
      nums.append(b);
    }
  }

  function rowFor(e) {
    const row = el("button", "caj-fila" + (e.id === st.openId ? " is-open" : ""));
    row.type = "button";
    row.append(el("span", "caj-c", e.control), el("span", "caj-nom", e.nombre), el("span", "caj-s", e.semestre),
      el("span", "caj-f", e.folio));
    const sig = e.siguiente;
    const nx = el("span", "caj-nx");
    nx.append(el("span", null, e.situacion === "sin_plan" ? "Sin plan" : sig ? fmtDate(sig.fecha) : "—"));
    let linea2 = "";
    if (e.situacion === "liquidada") linea2 = "Sin pagos pendientes";
    else if (sig) linea2 = `${pesos(sig.monto)} · ${sig.faltan === 1 ? "falta 1 pago" : `faltan ${sig.faltan} pagos`}`;
    nx.append(el("span", null, linea2));
    row.append(nx);
    const [sit, tono] = SITUACION[e.situacion] || [e.situacion, "gris"];
    row.append(el("span", "caj-st est-badge est-badge-" + tono, sit));
    return row;
  }

  function reiniciar() { st.page = 1; loadList(); }

  $("cajQ").addEventListener("input", (ev) => {
    const v = ev.target.value;
    $("cajQBox").classList.toggle("has-text", v.trim() !== "");
    $("cajQBorrar").hidden = v === "";
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => { st.q = v.trim(); reiniciar(); }, 300);
  });
  $("cajQBorrar").addEventListener("click", () => {
    $("cajQ").value = "";
    $("cajQ").dispatchEvent(new Event("input"));
    $("cajQ").focus();
  });
  $("cajSem").addEventListener("change", (ev) => {
    st.semestre = ev.target.value;
    ev.target.classList.toggle("is-set", !!st.semestre);
    $("cajSemHint").textContent = st.semestre ? `Solo en ${ev.target.selectedOptions[0].textContent}.` : "Busca en todos los semestres.";
    reiniciar();
  });
  $("cajOrden").addEventListener("change", (ev) => { st.orden = ev.target.value; reiniciar(); });
  $("cajFiltros").addEventListener("click", (ev) => {
    const b = ev.target.closest("button[data-f]");
    if (!b) return;
    st.filtro = b.dataset.f; reiniciar();
  });
  $("cajPrev").addEventListener("click", () => { st.page -= 1; loadList(); });
  $("cajNext").addEventListener("click", () => { st.page += 1; loadList(); });

  loadSemestres();
  loadList();
})();
