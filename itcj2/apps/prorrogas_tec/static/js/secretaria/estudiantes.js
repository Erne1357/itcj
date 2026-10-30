// Prórrogas · Estudiantes (vista de secretaría).
// Lista de aceptadas por semestre y expediente lateral: cuenta, plan, recibos, documentos e historial.
// APIs: /api/prorrogas/v2/estudiantes/*. Todo texto del servidor entra con textContent (nunca innerHTML).
(function () {
  "use strict";

  const root = document.querySelector(".est");
  if (!root) return;
  const API = root.dataset.api;
  const EST = "/estudiantes";
  const $ = (id) => document.getElementById(id);
  const MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];
  const PER_PAGE = 25;
  const FILTROS = ["todos", "con_adeudo", "al_corriente", "sin_plan", "liquidada"];
  const HIST = {
    solicitud_creada: "Solicitud creada", solicitud_aceptada: "Prórroga aceptada",
    plan_confirmado: "Plan de pagos confirmado", documento_generado: "Documento generado",
    documento_firmado: "Carta firmada por el estudiante", recibo_registrado: "Recibo registrado",
    recibo_anulado: "Recibo anulado", recordatorio_enviado: "Recordatorio enviado",
    desbloqueo_avisado: "Desbloqueo avisado",
  };

  const st = { period: null, q: "", filtro: "todos", page: 1, openId: null };
  let listSeq = 0;
  let openSeq = 0;
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

  // Las fechas ISO se leen por partes: new Date("2026-03-01") sería UTC y mostraría el día anterior.
  function fmtDate(iso) {
    if (!iso) return "—";
    const [y, m, d] = String(iso).slice(0, 10).split("-").map(Number);
    return `${d} ${MESES[m - 1]} ${y}`;
  }

  function todayIso() {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  }

  const cents = (v) => Math.round(parseFloat(v) * 100);
  const money = (c) => (isNaN(c) ? "—" : "$" + (c / 100).toLocaleString("es-MX", { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
  const pesos = (s) => money(cents(s));

  // Deshabilita el botón mientras corre fn y lo habilita en cualquier desenlace.
  async function busy(btn, fn) {
    if (btn.disabled) return;
    btn.disabled = true;
    try { await fn(); } catch (e) { toast("Ocurrió un error inesperado."); } finally { btn.disabled = false; }
  }

  function button(text, cls, onClick) {
    const b = el("button", cls || "sec-btn sec-btn-ghost est-sm", text);
    b.type = "button";
    b.addEventListener("click", () => busy(b, () => onClick(b)));
    return b;
  }

  // ── Lista ───────────────────────────────────────────────────────────
  async function loadPeriods() {
    const r = await api(EST + "/periodos");
    if (!r.ok) { show($("estError"), r.data.message || "No se pudieron cargar los semestres."); return; }
    const items = r.data.items || [];
    if (!items.length) { $("estMain").hidden = true; $("estSinPeriodos").hidden = false; return; }
    const sel = $("estPeriodo");
    items.forEach((p) => { const o = el("option", null, p.label); o.value = p.id; sel.append(o); });
    // Estadísticas enlaza con ?period_id=&filtro=; solo se aceptan valores conocidos.
    const qs = new URLSearchParams(location.search);
    const pedido = items.find((p) => String(p.id) === qs.get("period_id"));
    st.period = pedido ? pedido.id : r.data.actual != null ? r.data.actual : items[0].id;
    if (FILTROS.includes(qs.get("filtro"))) st.filtro = qs.get("filtro");
    sel.value = st.period;
    loadList();
  }

  async function loadList() {
    const seq = ++listSeq;
    const qs = new URLSearchParams({ period_id: st.period, filtro: st.filtro, page: st.page, per_page: PER_PAGE });
    if (st.q) qs.set("q", st.q);
    const r = await api(EST + "?" + qs);
    if (seq !== listSeq) return;
    if (!r.ok) { show($("estError"), r.data.message || "No se pudo cargar la lista."); return; }
    show($("estError"), "");
    renderList(r.data);
  }

  function renderList(d) {
    document.querySelectorAll("#estFiltros button").forEach((b) => {
      b.classList.toggle("is-active", b.dataset.f === st.filtro);
      b.querySelector("b").textContent = (d.conteos || {})[b.dataset.f] ?? 0;
    });
    const rows = $("estRows");
    rows.textContent = "";
    d.items.forEach((e) => rows.append(rowFor(e)));
    $("estVacio").hidden = d.items.length > 0;
    const pages = Math.max(1, Math.ceil(d.total / d.per_page));
    $("estMostrando").textContent = `Mostrando ${d.items.length} de ${d.total}`;
    $("estPagina").textContent = `Página ${d.page} de ${pages}`;
    $("estPrev").disabled = d.page <= 1;
    $("estNext").disabled = d.page >= pages;
  }

  function rowFor(e) {
    const row = el("div", "est-row" + (e.id === st.openId ? " is-open" : ""));
    row.tabIndex = 0;
    row.setAttribute("role", "button");
    row.append(el("span", "mono", e.control));
    const name = el("span", "est-name", e.nombre);
    if (e.avisar_desbloqueo) name.append(el("span", "est-tag", "Avisar desbloqueo"));
    row.append(name);

    const pagos = el("div", "est-pagos");
    const dots = el("div", "est-dots");
    (e.pagos || []).forEach((s) => dots.append(el("span", "est-dot est-dot-" + s)));
    pagos.append(dots);
    if ((e.pagos || []).length) pagos.append(el("span", "mono", `${e.pagados}/${e.pagos.length} pagados`));
    row.append(pagos);

    const f = el("div");
    if (e.situacion === "atrasada") f.append(el("span", "est-pill est-pill-alert", "Vencida desde " + fmtDate(e.vencida_desde)));
    else if (e.situacion === "al_corriente") f.append(el("span", "est-pill", `${e.faltantes} por pagar`));
    else if (e.situacion === "sin_plan") f.append(el("span", "est-pill est-pill-grey", "Sin plan"));
    else if (e.situacion === "liquidada") f.append(el("span", "est-check", "✓"));
    row.append(f);

    const c = el("div");
    const rec = button("Recordar", "sec-btn sec-btn-ghost est-sm", async () => {
      const r = await api(`${EST}/${e.id}/recordar`, { body: {} });
      loadList();   // también si falla: el botón vuelve a su estado real (puede_recordar)
      if (!r.ok) { toast(r.data.message || "No se pudo enviar el recordatorio."); return; }
      toast("Recordatorio enviado.");
      if (st.openId === e.id) renderPanel(r.data);
    });
    rec.disabled = !e.puede_recordar;
    rec.title = "Enviar recordatorio de pago por correo";
    rec.addEventListener("click", (ev) => ev.stopPropagation());
    c.append(rec);
    row.append(c);

    const open = () => openPanel(e.id);
    row.addEventListener("click", open);
    row.addEventListener("keydown", (ev) => { if (ev.key === "Enter" && ev.target === row) open(); });
    return row;
  }

  $("estPeriodo").addEventListener("change", (ev) => { st.period = ev.target.value; st.page = 1; closePanel(); loadList(); });
  $("estQ").addEventListener("input", (ev) => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => { st.q = ev.target.value.trim(); st.page = 1; loadList(); }, 300);
  });
  $("estFiltros").addEventListener("click", (ev) => {
    const b = ev.target.closest("button[data-f]");
    if (!b) return;
    st.filtro = b.dataset.f; st.page = 1; loadList();
  });
  $("estPrev").addEventListener("click", () => { st.page -= 1; loadList(); });
  $("estNext").addEventListener("click", () => { st.page += 1; loadList(); });

  $("estExport").addEventListener("click", (ev) => busy(ev.currentTarget, async () => {
    let r;
    try {
      r = await fetch(API + EST + "/adeudos.xlsx", {
        method: "POST", credentials: "include",
        headers: { "Content-Type": "application/json" }, body: JSON.stringify({ period_id: Number(st.period) }),
      });
    } catch (e) { toast("Sin conexión con el servidor."); return; }
    if (!r.ok) {
      const d = await r.json().catch(() => ({}));
      toast(d.message || "No se pudo exportar la lista.");
      return;
    }
    const blob = await r.blob();
    const m = /filename="([^"]+)"/.exec(r.headers.get("Content-Disposition") || "");
    const url = URL.createObjectURL(blob);
    const a = el("a");
    a.href = url;
    a.download = m ? m[1] : "adeudos.xlsx";
    document.body.append(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    toast("Lista de adeudos exportada.");
    loadList();   // la exportación marca las solicitudes como bloqueadas
  }));

  // ── Expediente ──────────────────────────────────────────────────────
  async function openPanel(id) {
    const seq = ++openSeq;
    st.openId = id;
    document.querySelectorAll(".est-row.is-open").forEach((n) => n.classList.remove("is-open"));
    $("estPanel").hidden = false;
    $("estPanelBody").textContent = "Cargando…";
    const r = await api(`${EST}/${id}`);
    if (seq !== openSeq) return;
    if (!r.ok) { $("estPanelBody").textContent = r.data.message || "No se pudo cargar el expediente."; return; }
    renderPanel(r.data);
    loadList();   // marca la fila abierta
  }

  function closePanel() {
    openSeq += 1;
    st.openId = null;
    $("estPanel").hidden = true;
    document.querySelectorAll(".est-row.is-open").forEach((n) => n.classList.remove("is-open"));
  }
  $("estPanelClose").addEventListener("click", closePanel);
  document.addEventListener("keydown", (ev) => { if (ev.key === "Escape" && !$("estPanel").hidden) closePanel(); });

  function section(title) {
    const s = el("section", "est-sec");
    s.append(el("h3", null, title));
    return s;
  }

  function kv(pairs) {
    const dl = el("dl", "sol-dl");
    pairs.forEach(([k, v]) => { dl.append(el("dt", null, k), el("dd", null, v)); });
    return dl;
  }

  function field(label, input) {
    const l = el("label", "est-field");
    l.append(el("span", null, label), input);
    return l;
  }

  function input(type, attrs) {
    const i = el("input");
    i.type = type;
    Object.entries(attrs || {}).forEach(([k, v]) => i.setAttribute(k, v));
    return i;
  }

  const SITUACION = { sin_plan: "Sin plan", liquidada: "Liquidada", atrasada: "Con adeudo", al_corriente: "Al corriente" };

  // Datos de un evento en líneas legibles: escalares juntos; cada objeto de una lista en su propia línea
  // (parcialidades: "#1 $1,000.00 · 1 feb 2091"); cualquier otro objeto, en JSON.
  function histLineas(datos) {
    const esObj = (v) => v != null && typeof v === "object";
    const item = (i) => (esObj(i) && "numero" in i ? `#${i.numero} ${pesos(i.monto)} · ${fmtDate(i.fecha)}`
      : esObj(i) ? JSON.stringify(i) : String(i));
    const cortos = [], lineas = [];
    Object.entries(datos || {}).forEach(([k, v]) => {
      if (Array.isArray(v) && v.some(esObj)) lineas.push(`${k}:`, ...v.map(item));
      else cortos.push(`${k}: ${Array.isArray(v) ? v.join(", ") || "—" : esObj(v) ? JSON.stringify(v) : v}`);
    });
    return (cortos.length ? [cortos.join(" · ")] : []).concat(lineas);
  }

  function renderPanel(x) {
    const body = $("estPanelBody");
    body.textContent = "";
    const s = x.solicitud, e = x.estudiante, c = x.cuenta;
    $("estPanelTitulo").textContent = e.nombre;
    const msg = el("div", "est-error");
    msg.setAttribute("role", "alert");
    msg.hidden = true;

    // Datos y cuenta
    const a = section("Cuenta");
    a.append(kv([
      ["Folio", s.folio], ["No. de control", e.control], ["Correo", e.correo], ["Carrera", e.carrera],
      ["Semestre", s.semestre], ["Plazos solicitados", s.plazos ?? "—"], ["Motivo", s.motivo || "—"],
      ["Total", c.total != null ? pesos(c.total) : "—"], ["Pagado", pesos(c.pagado)],
      ["Saldo", c.saldo != null ? pesos(c.saldo) : "—"], ["Situación", SITUACION[c.situacion] || c.situacion],
    ]));
    if (s.comentario) a.append(el("p", "est-note", s.comentario));
    body.append(msg, a);

    // Un expediente nuevo reemplaza el panel y vuelve a pintar la fila.
    const apply = (r, okMsg) => {
      if (!r.ok) { show(msg, r.data.message || "No se pudo completar la acción."); return false; }
      toast(okMsg);
      renderPanel(r.data);
      loadList();
      return true;
    };

    body.append(planSection(x, msg, apply), recibosSection(x, msg, apply), docsSection(x));

    const bl = x.bloqueo || {}, rec = x.recordatorio || {};
    const b = section("Bloqueo y recordatorios");
    b.append(kv([
      ["Lista de adeudos", bl.exportada ? "Exportado el " + fmtDate(bl.exportada) : "No"],
      ["Desbloqueo avisado", bl.avisado ? fmtDate(bl.avisado) : "No"],
      ["Último recordatorio", rec.ultimo ? fmtDate(rec.ultimo) : "Nunca"],
    ]));
    if (bl.avisar_desbloqueo) {
      b.append(el("p", null, "La cuenta quedó liquidada y estaba en la lista de bloqueo."));
      b.append(button("Avisar desbloqueo", "sec-btn est-sm", async () => {
        show(msg, "");
        apply(await api(`${EST}/${s.id}/desbloqueo-avisado`, { body: {} }), "Desbloqueo avisado.");
      }));
    }
    body.append(b);

    const h = section("Historial");
    const ul = el("ul", "est-hist");
    (x.historial || []).forEach((ev) => {
      const li = el("li");
      li.append(el("b", null, HIST[ev.tipo] || ev.tipo), el("span", null, fmtDate(ev.fecha)));
      histLineas(ev.datos).forEach((t) => li.append(el("small", null, t)));
      ul.append(li);
    });
    h.append(ul);
    body.append(h);
  }

  // ── Plan ────────────────────────────────────────────────────────────
  function planSection(x, msg, apply) {
    const s = x.solicitud, c = x.cuenta, p = x.plan;
    const sec = section("Plan de pagos");
    const keptNums = new Set(p.conservadas || []);
    const vigentes = c.parcialidades || [];
    if (vigentes.length) {
      const ul = el("ul", "est-plan");
      vigentes.forEach((q) => {
        const li = el("li");
        li.append(el("span", "est-dot est-dot-" + q.estado), el("span", null, `${q.numero}. ${pesos(q.monto)}`),
          el("span", null, fmtDate(q.fecha)), el("small", null, `cubierto ${pesos(q.cubierto)}`));
        ul.append(li);
      });
      sec.append(ul);
    }
    if (!p.puede_replantear) {   // liquidada o fuera del semestre, haya plan o no
      sec.append(el("p", "est-note", c.situacion === "liquidada"
        ? "Cuenta liquidada." : "El semestre terminó: ya no se puede armar ni replantear el plan."));
      return sec;
    }

    const replan = p.confirmado;
    sec.append(el("h4", null, replan ? "Replantear lo que falta" : "Crear plan"));
    const maxN = replan ? p.max_nuevas : 3;
    const total = input("text", { inputmode: "decimal", "aria-label": "Total" });
    total.value = replan ? c.total : "";
    const n = el("select");
    for (let i = 1; i <= maxN; i++) { const o = el("option", null, String(i)); o.value = i; n.append(o); }
    const rowsBox = el("div", "est-plan-rows");
    const restante = el("p", "est-note");
    const minD = todayIso();
    let planSeq = 0;
    let confirmBtn = null;

    const paintRest = () => {
      const ms = [...rowsBox.querySelectorAll("input[data-m]")];
      const base = cents(total.value) - (replan ? cents(p.suma_conservadas) : 0);
      const sum = ms.reduce((t, i) => t + cents(i.value), 0);
      restante.textContent = replan
        ? `Falta por repartir: ${money(base)}. Suma de las nuevas: ${money(sum)}.`
        : `Suma de las parcialidades: ${money(sum)}.`;
    };

    // Las filas se arman al instante desde n; el reparto sugerido solo rellena montos si sigue siendo la reconstrucción vigente.
    const rebuild = async () => {
      const my = ++planSeq;
      rowsBox.textContent = "";
      const count = Number(n.value);
      const base = cents(total.value) - (replan ? cents(p.suma_conservadas) : 0);
      for (let i = 0; i < count; i++) {
        const m = input("text", { inputmode: "decimal", "data-m": "1", "aria-label": `Monto de la parcialidad ${i + 1}` });
        m.addEventListener("input", paintRest);
        const f = input("date", { min: minD, "data-f": "1", "aria-label": `Fecha de la parcialidad ${i + 1}` });
        if (p.fecha_limite) f.max = p.fecha_limite;
        const r = el("div", "est-plan-row");
        r.append(el("span", null, `${(replan ? keptNums.size : 0) + i + 1}.`), m, f);
        rowsBox.append(r);
      }
      paintRest();
      if (confirmBtn) confirmBtn.disabled = base > 0;   // sin reparto en vuelo, el botón queda libre
      if (!(base > 0)) return;
      const r = await api(`${EST}/reparto?total=${(base / 100).toFixed(2)}&n=${count}`);
      if (my !== planSeq) return;   // una reconstrucción más nueva ya decide el estado del botón
      if (confirmBtn) confirmBtn.disabled = false;
      if (!r.ok) return;
      [...rowsBox.querySelectorAll("input[data-m]")].forEach((m, i) => { m.value = (r.data.montos || [])[i] || ""; });
      paintRest();
    };
    total.addEventListener("change", rebuild);
    n.addEventListener("change", rebuild);

    sec.append(field("Total del adeudo", total), field(replan ? "Parcialidades nuevas" : "Parcialidades", n));
    if (replan) sec.append(el("p", "est-note", `Conservadas (solo lectura): ${[...keptNums].join(", ")} · ${pesos(p.suma_conservadas)}`));
    sec.append(rowsBox, restante);
    confirmBtn = button(replan ? "Confirmar nuevo plan" : "Confirmar plan", "sec-btn est-sm", async () => {
      show(msg, "");
      const parc = [...rowsBox.querySelectorAll(".est-plan-row")].map((row) => ({
        monto: row.querySelector("input[data-m]").value.trim(), fecha: row.querySelector("input[data-f]").value }));
      if (parc.some((q) => !q.fecha)) { show(msg, "Falta la fecha de una parcialidad."); return; }
      apply(await api(`${EST}/${s.id}/plan`, { body: { total: total.value.trim(), parcialidades: parc } }), "Plan confirmado.");
    });
    sec.append(confirmBtn);
    if (total.value) rebuild();
    return sec;
  }

  // ── Recibos ─────────────────────────────────────────────────────────
  function recibosSection(x, msg, apply) {
    const s = x.solicitud;
    const sec = section("Recibos de Caja");
    const ul = el("ul", "est-recibos");
    (x.recibos || []).forEach((r) => {
      const li = el("li", r.anulado ? "is-void" : "");
      li.append(el("b", "mono", r.folio), el("span", null, fmtDate(r.fecha)), el("span", null, pesos(r.monto)));
      if (r.anulado) li.append(el("small", null, "Anulado: " + (r.motivo_anulacion || "")));
      else li.append(button("Anular", "sec-btn sec-btn-ghost est-sm", async () => {
        const motivo = prompt("Motivo de la anulación (mínimo 5 caracteres):");
        if (motivo == null) return;
        show(msg, "");
        apply(await api(`${EST}/${s.id}/recibos/${r.id}/anular`, { body: { motivo: motivo.trim() } }), "Recibo anulado.");
      }));
      ul.append(li);
    });
    if (!ul.children.length) sec.append(el("p", "est-note", "Sin recibos."));
    sec.append(ul);
    if (x.cuenta.total == null) return sec;  // como el sin_plan del servicio: las del Excel tienen plan sin confirmar

    const folio = input("text", { maxlength: "40" });
    const fecha = input("date", { max: todayIso() });
    fecha.value = todayIso();
    const monto = input("text", { inputmode: "decimal" });
    const form = el("div", "est-recibo-form");
    form.append(field("Folio de Caja", folio), field("Fecha de pago", fecha), field("Monto", monto));
    form.append(button("Registrar recibo", "sec-btn est-sm", async () => {
      show(msg, "");
      if (!fecha.value) { show(msg, "Falta la fecha de pago."); return; }
      apply(await api(`${EST}/${s.id}/recibos`, { body: { folio: folio.value.trim(), fecha: fecha.value, monto: monto.value.trim() } }), "Recibo registrado.");
    }));
    sec.append(form);
    return sec;
  }

  // ── Documentos ──────────────────────────────────────────────────────
  function docsSection(x) {
    const s = x.solicitud;
    const sec = section("Documentos");
    const ul = el("ul", "est-docs");
    (s.documentos || []).forEach((d) => {
      const li = el("li");
      li.append(el("span", null, `${d.label} (v${d.version})`));
      const a = el("a", null, "Ver / imprimir");
      a.href = `${API}/solicitudes/${s.id}/documentos/${d.id}.pdf`;
      a.target = "_blank";
      a.rel = "noopener";
      li.append(a);
      if (d.firmado) li.append(el("small", null, "Firmado"));
      else if (String(d.tipo).startsWith("carta_compromiso")) li.append(el("small", "est-pend", "Firma pendiente"));
      ul.append(li);
    });
    if (!ul.children.length) sec.append(el("p", "est-note", "Sin documentos."));
    sec.append(ul);
    return sec;
  }

  loadPeriods();
})();
