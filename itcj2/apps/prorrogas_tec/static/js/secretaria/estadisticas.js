// Prórrogas · Estadísticas (vista de secretaría).
// APIs: /api/prorrogas/v2/estadisticas/*. Todo texto del servidor entra con textContent (nunca innerHTML);
// las etiquetas de Chart.js se dibujan en canvas.
(function () {
  "use strict";

  const root = document.querySelector(".stt");
  if (!root) return;
  const API = root.dataset.api;
  const $ = (id) => document.getElementById(id);
  const WINE = "#652F2A", RED = "#c4541f", ORANGE = "#F27340", BLUE = "#6799E0";
  const CARRERA_COLORS = [WINE, BLUE, ORANGE, "#2f8f83", "#9a6fb0", "#c9a227", "#6b7a8f", "#b5524a"];
  const MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];

  const st = { sem: "", gran: "semanal", data: null };
  const charts = {};
  let seq = 0;

  function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  async function api(path, opts) {
    const o = Object.assign({ credentials: "include" }, opts);
    let r;
    try { r = await fetch(API + path, o); } catch (e) { return { ok: false, status: 0, data: { message: "Sin conexión con el servidor." } }; }
    const data = await r.json().catch(() => ({}));
    return { ok: r.ok, status: r.status, data };
  }

  function show(node, msg) { node.textContent = msg || ""; node.hidden = !msg; }

  function toast(msg) {
    const t = $("secToast");
    t.textContent = msg;
    t.hidden = false;
    clearTimeout(toast.t);
    toast.t = setTimeout(() => { t.hidden = true; }, 3500);
  }

  async function busy(btn, fn) {
    if (btn.disabled) return;
    btn.disabled = true;
    try { await fn(); } catch (e) { toast("Ocurrió un error inesperado."); } finally { btn.disabled = false; }
  }

  const num = (v) => (v == null ? "—" : String(v));
  const pct = (n, d) => (d ? Math.round((n * 100) / d) + "%" : "—");
  // Dinero: la cadena de 2 decimales se separa en miles sin pasar por float.
  const money = (s) => (s == null ? "—" : "$" + String(s).replace(/\B(?=(\d{3})+(?!\d))/g, ","));
  const dias = (v) => (v == null ? "—" : String(v));

  function labelSemana(iso) {
    const [, m, d] = String(iso).split("-").map(Number);
    return `${d} ${MESES[m - 1]}`;
  }
  function labelMes(ym) {
    const [y, m] = String(ym).split("-").map(Number);
    return `${MESES[m - 1]} ${y}`;
  }

  // Destruye la gráfica anterior para que no se apilen al cambiar de semestre.
  function draw(key, canvasId, config) {
    if (charts[key]) { charts[key].destroy(); delete charts[key]; }
    if (!window.Chart) return false;
    charts[key] = new window.Chart($(canvasId), config);
    return true;
  }

  // ── Carga ───────────────────────────────────────────────────────────
  async function loadSemesters() {
    const r = await api("/semestres");
    const sel = $("sttSem");
    const todos = el("option", null, "Todos");
    todos.value = "";
    sel.append(todos);
    if (!r.ok) { show($("sttError"), r.data.message || "No se pudieron cargar los semestres."); }
    else {
      (r.data.items || []).forEach((s) => { const o = el("option", null, s.label); o.value = s.label; sel.append(o); });
      st.sem = r.data.actual || "";
    }
    sel.value = st.sem;
    sel.addEventListener("change", () => { st.sem = sel.value; load(); });
    load();
  }

  async function load() {
    const my = ++seq;
    const r = await api("?" + new URLSearchParams({ semestre: st.sem }));
    if (my !== seq) return;
    if (!r.ok) { show($("sttError"), r.data.message || "No se pudieron cargar las estadísticas."); return; }
    show($("sttError"), "");
    st.data = r.data;
    render(r.data);
  }

  function render(d) {
    $("sttTotal").textContent = `${st.sem ? st.sem + " · " : ""}${num(d.total)} solicitudes`;
    renderDonut(d);
    renderAceptacion(d.aceptacion || {});
    renderLinea();
    renderKpis(d.kpis || {});
    renderCumplimiento(d.cumplimiento || {});
    renderTabla(d.por_carrera || []);
  }

  function renderDonut(d) {
    const cs = d.por_carrera || [];
    const leyenda = $("sttLeyenda");
    leyenda.textContent = "";
    cs.forEach((c, i) => {
      const li = el("li");
      const sw = el("span", "stt-sw");
      sw.style.background = CARRERA_COLORS[i % CARRERA_COLORS.length];
      li.append(sw, el("span", "stt-lbl", c.carrera), el("b", null, num(c.solicitudes)));
      leyenda.append(li);
    });
    // Sin Chart.js la leyenda ya muestra los números en texto.
    const ok = draw("donut", "sttDonut", {
      type: "doughnut",
      data: { labels: cs.map((c) => c.carrera), datasets: [{ data: cs.map((c) => c.solicitudes), backgroundColor: cs.map((_, i) => CARRERA_COLORS[i % CARRERA_COLORS.length]) }] },
      options: { cutout: "65%", maintainAspectRatio: false, plugins: { legend: { display: false } } },
    });
    $("sttDonut").hidden = !ok;
  }

  function renderAceptacion(a) {
    const ac = a.aceptadas || 0, re = a.rechazadas || 0;
    const p = a.pct_aceptadas;
    $("sttAcPct").textContent = p == null ? "—" : p + "%";
    $("sttRePct").textContent = p == null ? "—" : (100 - p) + "%";
    $("sttAcN").textContent = `${ac} solicitudes`;
    $("sttReN").textContent = `${re} solicitudes`;
    $("sttAcBar").style.width = (p == null ? 0 : p) + "%";
    $("sttReBar").style.width = (p == null ? 0 : 100 - p) + "%";
  }

  function renderLinea() {
    const d = st.data;
    if (!d) return;
    const mensual = st.gran === "mensual";
    const pts = ((d.linea || {})[st.gran]) || [];
    const labels = pts.map((p) => (mensual ? labelMes(p.mes) : labelSemana(p.inicio)));
    $("sttGranLabel").textContent = mensual ? "mes" : "semana";
    document.querySelectorAll("#sttGran button").forEach((b) => b.classList.toggle("is-active", b.dataset.g === st.gran));
    const ok = draw("linea", "sttLinea", {
      type: "bar",
      data: {
        labels,
        datasets: [
          { label: "Aceptadas", data: pts.map((p) => p.aceptadas), backgroundColor: WINE, stack: "s" },
          { label: "Rechazadas", data: pts.map((p) => p.rechazadas), backgroundColor: RED, stack: "s" },
        ],
      },
      options: {
        maintainAspectRatio: false,
        scales: { x: { stacked: true, grid: { display: false } }, y: { stacked: true, beginAtZero: true, ticks: { precision: 0 } } },
        plugins: { legend: { position: "bottom" } },
      },
    });
    $("sttLinea").hidden = !ok;
    const txt = $("sttLineaTxt");
    txt.textContent = "";
    txt.hidden = ok;
    if (!ok) pts.forEach((p, i) => txt.append(el("div", null, `${labels[i]}: ${p.aceptadas} aceptadas, ${p.rechazadas} rechazadas`)));
  }

  function renderKpis(k) {
    const items = [
      ["Solicitudes pendientes", num(k.pendientes), k.pendiente_mas_vieja_dias == null ? "" : `la más antigua: ${k.pendiente_mas_vieja_dias} días`],
      ["Tiempo promedio de respuesta", dias(k.respuesta_promedio_dias), "días"],
      ["Monto total prorrogado", money(k.monto_total), ""],
      ["Plazos promedio", num(k.plazos_promedio), "parcialidades por prórroga"],
      ["Solicitudes replanteadas", num(k.replanteadas), ""],
    ];
    const box = $("sttKpis");
    box.textContent = "";
    items.forEach(([label, value, note]) => {
      const c = el("div", "stt-card stt-kpi");
      c.append(el("div", "stt-sub", label), el("div", "stt-kpi-v", value), el("div", "stt-note", note));
      box.append(c);
    });
  }

  function renderCumplimiento(c) {
    const venc = c.vencidas || 0;
    const parts = [
      ["Pagó en fecha acordada", c.a_tiempo, BLUE],
      ["Pagó tarde", c.tarde, WINE],
      ["Sin pago", c.sin_pago, ORANGE],
    ];
    $("sttCumpSub").textContent = `De ${venc} parcialidades vencidas`;
    const stack = $("sttStack");
    const cumps = $("sttCumps");
    stack.textContent = "";
    cumps.textContent = "";
    parts.forEach(([label, n, color]) => {
      const seg = el("div");
      seg.style.flex = String(n || 0);
      seg.style.background = color;
      stack.append(seg);
      const b = el("div");
      const sw = el("span", "stt-sw");
      sw.style.background = color;
      const h = el("div", "stt-cump-l");
      h.append(sw, el("span", null, label));
      b.append(h, el("div", "stt-cump-v", pct(n || 0, venc)), el("div", "stt-note", `${num(n)} parcialidades`));
      cumps.append(b);
    });
    $("sttSinPago").textContent = `${num(c.estudiantes_sin_pago)} estudiantes con prórroga vencida sin pago`;
    $("sttVer").hidden = c.period_id == null;
  }

  function renderTabla(rows) {
    const box = $("sttRows");
    box.textContent = "";
    $("sttVacio").hidden = rows.length > 0;
    rows.forEach((c, i) => {
      const row = el("div", "stt-row");
      const name = el("span", "stt-name");
      const sw = el("span", "stt-sw");
      sw.style.background = CARRERA_COLORS[i % CARRERA_COLORS.length];
      name.append(sw, el("span", null, c.carrera));
      const decididas = (c.aceptadas || 0) + (c.rechazadas || 0);
      const pctAc = decididas ? Math.round((c.aceptadas * 100) / decididas) : null;
      const pagadas = (c.a_tiempo || 0) + (c.tarde || 0);
      const pctPago = c.vencidas ? Math.round((pagadas * 100) / c.vencidas) : null;
      row.append(name, el("span", "stt-mono", num(c.solicitudes)), meter(pctAc, BLUE), el("span", "stt-mono", money(c.monto)), meter(pctPago, WINE));
      box.append(row);
    });
  }

  function meter(p, color) {
    const w = el("div", "stt-meter");
    const track = el("div", "stt-track");
    const fill = el("i");
    fill.style.width = (p == null ? 0 : p) + "%";
    fill.style.background = color;
    track.append(fill);
    w.append(track, el("span", "stt-mono", p == null ? "—" : p + "%"));
    return w;
  }

  // ── Interacciones ───────────────────────────────────────────────────
  document.querySelectorAll("#sttGran button").forEach((b) => b.addEventListener("click", () => { st.gran = b.dataset.g; renderLinea(); }));

  const exp = $("sttExport");
  exp.addEventListener("click", () => busy(exp, async () => {
    let r;
    try { r = await fetch(API + "/detalle.csv?" + new URLSearchParams({ semestre: st.sem }), { credentials: "include" }); }
    catch (e) { toast("Sin conexión con el servidor."); return; }
    if (!r.ok) {
      const d = await r.json().catch(() => ({}));
      toast(d.message || "No se pudo exportar.");
      return;
    }
    const blob = await r.blob();
    const m = /filename="([^"]+)"/.exec(r.headers.get("Content-Disposition") || "");
    const url = URL.createObjectURL(blob);
    const a = el("a");
    a.href = url;
    a.download = m ? m[1] : "estadisticas-prorrogas.csv";
    document.body.append(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }));

  loadSemesters();
})();
