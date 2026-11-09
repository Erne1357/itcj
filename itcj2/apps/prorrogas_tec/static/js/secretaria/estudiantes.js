// Prórrogas · Estudiantes (vista de secretaría).
// Lista de aceptadas por semestre y expediente en modal: plan de pagos, solicitud y documentos, historial.
// APIs: /api/prorrogas/v2/estudiantes/*. Todo texto del servidor entra con textContent (nunca innerHTML).
(function () {
  "use strict";

  const root = document.querySelector(".est");
  if (!root) return;
  const API = root.dataset.api;
  const EST = "/estudiantes";
  const $ = (id) => document.getElementById(id);
  const perms = (document.body.dataset.perms || "").split(" ");
  const can = (p) => perms.includes("*") || perms.includes(p);
  const MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];
  const PER_PAGE = 25;
  const PLANES = "prorrogas_tec.plans.api.manage";
  const REMIND = "prorrogas_tec.students.api.remind";
  const FILTROS = ["todos", "con_adeudo", "al_corriente", "sin_plan", "liquidada", "por_firmar", "pendiente_cierre"];
  const HIST = {
    solicitud_creada: "Solicitud creada", solicitud_aceptada: "Prórroga aceptada",
    plan_confirmado: "Plan de pagos creado", plan_modificado: "Plan de pagos modificado",
    documento_generado: "Documento generado",
    documento_firmado: "Carta firmada por el estudiante", recibo_registrado: "Recibo registrado",
    recibo_anulado: "Recibo anulado", recordatorio_enviado: "Recordatorio enviado",
    desbloqueo_avisado: "Desbloqueo avisado", recordatorio_pendiente: "Recordatorio de pendiente enviado", correo_no_enviado: "Correo sin enviar", referencia_subida: "Referencia bancaria subida", cerrada_sin_plan: "Cerrada sin plan",
  };

  const AVISO = {
    aceptada: "aceptación", rechazada: "rechazo", carta_lista: "carta lista", plan_modificado: "cambio de plan",
    recordatorio: "recordatorio de pago", firma_pendiente: "firma pendiente", referencia_pendiente: "referencia pendiente",
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
    if (r.status === 403 && !data.message) data.message = "No tienes permiso para esta acción.";
    return { ok: r.ok, status: r.status, data };
  }

  function show(node, msg) { node.textContent = msg || ""; node.hidden = !msg; }

  function toast(msg) {
    const t = $(dlg.open ? "estToast" : "secToast");   // el modal tapa el aviso de la página
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
    if (e.por_firmar) name.append(el("span", "est-tag", "Falta firma"));
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
    else if (e.situacion === "sin_plan") f.append(el("span", "est-pill est-pill-grey", e.pendiente_cierre ? "Cerrar sin plan" : "Sin plan"));
    else if (e.situacion === "liquidada") f.append(el("span", "est-check", "✓"));
    row.append(f);

    const c = el("div");
    const rec = button("Recordar", "sec-btn sec-btn-ghost est-sm", async () => {
      const r = await api(`${EST}/${e.id}/recordar`, { body: {} });
      loadList();   // también si falla: el botón vuelve a su estado real (puede_recordar)
      if (!r.ok) { toast(r.data.message || "No se pudo enviar el recordatorio."); return; }
      toast("Recordatorio enviado.");
      if (st.openId === e.id) render(r.data);
    });
    rec.disabled = !e.puede_recordar;
    rec.title = "Enviar recordatorio de pago por correo";
    rec.addEventListener("click", (ev) => ev.stopPropagation());
    if (can("prorrogas_tec.students.api.remind")) c.append(rec);
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

  if (!can("prorrogas_tec.students.api.export")) $("estExport").hidden = true;
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

  // ── Expediente (modal) ──────────────────────────────────────────────
  const dlg = $("estDialog");
  const OPCIONES = [1, 2];   // pagos que se ofrecen al armar el plan (como en la solicitud)
  const SITUACION = {
    sin_plan: ["Sin plan", "gris"], al_corriente: ["Al corriente", "azul"],
    atrasada: ["Con adeudo", "naranja"], liquidada: ["Liquidada", "vino"],
  };
  const PUNTO = {
    recibo_registrado: "azul", recibo_anulado: "naranja", plan_confirmado: "vino", plan_modificado: "vino",
    solicitud_aceptada: "vino", solicitud_creada: "tinta", recordatorio_enviado: "naranja", desbloqueo_avisado: "vino",
  };
  const ui = { tab: "plan", x: null, modificando: false, borrador: null };

  const plural = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;
  const debe = (q) => money(cents(q.monto) - cents(q.cubierto));
  const pagoLabel = (i, n) => (n === 1 ? "Pago único" : `Pago ${i}/${n}`);

  function icon(id) { return $(id).content.firstElementChild.cloneNode(true); }

  function fmtShort(iso) {
    if (!iso) return "—";
    const [y, m, d] = String(iso).slice(0, 10).split("-").map(Number);
    return `${d} ${MESES[m - 1]}` + (y === new Date().getFullYear() ? "" : ` ${y}`);
  }

  function fmtDateTime(iso) {
    const t = String(iso || "").slice(11, 16);
    return fmtDate(iso) + (t ? `, ${t}` : "");
  }

  function diasDesde(iso) {
    const [y, m, d] = String(iso).slice(0, 10).split("-").map(Number);
    const h = new Date();
    return Math.round((Date.UTC(h.getFullYear(), h.getMonth(), h.getDate()) - Date.UTC(y, m - 1, d)) / 864e5);
  }

  async function openPanel(id) {
    const seq = ++openSeq;
    if (st.openId !== id) Object.assign(ui, { tab: "plan", modificando: false, borrador: null });
    st.openId = id;
    if (!dlg.open) {
      $("estNombre").textContent = "Cargando…";
      ["estBadge", "estControl", "estCarrera"].forEach((k) => { $(k).textContent = ""; });
      $("estSinPlan").hidden = $("estSum").hidden = true;
      ["plan", "sol", "hist"].forEach((k) => { $("estPane-" + k).textContent = ""; });
      dlg.showModal();
    }
    const r = await api(`${EST}/${id}`);
    if (seq !== openSeq) return;
    if (!r.ok) { show($("estMsg"), r.data.message || "No se pudo cargar el expediente."); return; }
    render(r.data);
    if (r.data.correo_enviado === false) show($("estMsg"), "El último correo al estudiante no salió. Avísale por otro medio.");
    loadList();   // marca la fila abierta
  }

  function closePanel() { if (dlg.open) dlg.close(); }
  dlg.addEventListener("close", () => {   // también con Esc
    openSeq += 1;
    st.openId = null;
    document.querySelectorAll(".est-row.is-open").forEach((n) => n.classList.remove("is-open"));
  });
  $("estClose").addEventListener("click", closePanel);
  dlg.addEventListener("click", (ev) => { if (ev.target === dlg) closePanel(); });
  document.querySelectorAll(".est-tabs [data-tab]").forEach((b) => b.addEventListener("click", () => {
    ui.tab = b.dataset.tab;
    paintTab();
  }));

  // Un expediente nuevo (respuesta de cada acción) repinta el modal y la fila.
  function apply(r, okMsg) {
    if (!r.ok) { show($("estMsg"), r.data.message || "No se pudo completar la acción."); return false; }
    toast(okMsg);
    render(r.data);
    if (r.data.correo_enviado === false) show($("estMsg"), "Se guardó, pero el correo al estudiante no salió. Avísale por otro medio.");
    loadList();
    return true;
  }

  function render(x) {
    ui.x = x;
    const s = x.solicitud, e = x.estudiante, c = x.cuenta;
    const [sit, tono] = SITUACION[c.situacion] || [c.situacion, "gris"];
    $("estNombre").textContent = e.nombre;
    $("estBadge").textContent = sit;
    $("estBadge").className = "est-badge est-badge-" + tono;
    $("estControl").textContent = e.control;
    $("estCarrera").textContent = e.carrera || "";
    show($("estMsg"), "");
    const sinPlan = !c.parcialidades.length;
    $("estSinPlan").hidden = !sinPlan;
    $("estSinPlanTxt").textContent = `Prórroga aceptada el ${fmtDate(s.decidida)}`
      + (s.plazos ? ` · pidió ${plural(s.plazos, "pago")}.` : ".");
    $("estSum").hidden = sinPlan;
    if (!sinPlan) summary(c);
    $("estTab-sol").querySelector("b").textContent = (s.documentos || []).length || "";
    $("estTab-hist").querySelector("b").textContent = (x.historial || []).length || "";
    paintTab();
  }

  function summary(c) {
    const ps = c.parcialidades, n = ps.length, saldo = cents(c.saldo);
    $("estSumLabel").textContent = saldo > 0 ? "Le falta pagar" : "Pagó en total";
    $("estSumValor").textContent = money(saldo > 0 ? saldo : cents(c.total));
    $("estSumValor").classList.toggle("is-done", !(saldo > 0));
    $("estSumDe").textContent = saldo > 0 ? `de ${pesos(c.total)}` : "";
    const segs = $("estSegs");
    segs.textContent = "";
    ps.forEach((q) => segs.append(el("span", "est-seg est-seg-" + q.estado)));
    $("estSumAvance").textContent = `${ps.filter((q) => q.estado === "pagada").length} de ${n} pagos cubiertos`;

    const venc = ps.find((q) => q.estado === "vencida"), prox = ps.find((q) => q.estado !== "pagada");
    const [label, valor, sub] = venc ? ["Pago vencido", `${fmtShort(venc.fecha)} · hace ${plural(diasDesde(venc.fecha), "día")}`,
      `${debe(venc)} · ${pagoLabel(venc.numero, n).toLowerCase()}`]
      : prox ? ["Siguiente pago", fmtShort(prox.fecha), `${debe(prox)} · ${pagoLabel(prox.numero, n).toLowerCase()}`]
        : ["Liquidado el", fmtShort(ps[n - 1].pagado_el), "Ya no debe nada"];
    $("estProxLabel").textContent = label;
    $("estProxValor").textContent = valor;
    $("estProxSub").textContent = sub;
    $("estProx").className = "est-prox" + (venc ? " is-alert" : prox ? "" : " is-done");
  }

  function paintTab() {
    ["plan", "sol", "hist"].forEach((k) => {
      const on = k === ui.tab;
      $("estTab-" + k).classList.toggle("is-active", on);
      $("estTab-" + k).setAttribute("aria-selected", String(on));
      $("estPane-" + k).hidden = !on;
    });
    const pane = $("estPane-" + ui.tab);
    pane.textContent = "";
    if (ui.x) pane.append(ui.tab === "plan" ? planPane(ui.x) : ui.tab === "sol" ? solPane(ui.x) : histPane(ui.x));
  }

  function card(title, cls) {
    const c = el("section", "est-card" + (cls ? " " + cls : ""));
    if (title) c.append(el("h3", null, title));
    return c;
  }

  function input(type, attrs) {
    const i = el("input");
    i.type = type;
    Object.entries(attrs || {}).forEach(([k, v]) => i.setAttribute(k, v));
    return i;
  }

  // ── Plan ────────────────────────────────────────────────────────────
  function planPane(x) {
    const c = x.cuenta, wrap = el("div", "est-plan");
    if (!c.parcialidades.length || ui.modificando) {
      if (x.plan.editable) {
        wrap.append(can(PLANES) ? planForm(x) : el("p", "est-note", "Aún no tiene plan de pagos."));
      }
      else wrap.append(el("p", "est-note", x.solo_lectura
        ? "Prórroga del histórico sin semestre: solo cuenta para Estadísticas."
        : "El semestre terminó: ya no se puede crear el plan."));
      if (x.plan.cerrable && can(PLANES)) wrap.append(cierreCard(x));
      return wrap;
    }
    wrap.classList.add("has-side");
    const main = el("div", "est-plan-main");
    main.append(pagosHead(x));
    c.parcialidades.forEach((q) => main.append(pagoRow(q, c.parcialidades.length)));
    main.append(recibosCard(x));
    wrap.append(main, situacionCard(x));
    return wrap;
  }

  // Aceptada que terminó el semestre sin plan: la secretaria la cierra con motivo escrito (no se avisa al alumno).
  function cierreCard(x) {
    const card = el("div", "est-card");
    const motivo = el("textarea");
    motivo.rows = 3;
    motivo.maxLength = 1000;
    motivo.placeholder = "Motivo del cierre (mínimo 10 caracteres)";
    card.append(el("h3", null, "Cerrar sin plan"), motivo, button("Cerrar sin plan", "sec-btn est-sm", async () => {
      const r = await api(`${EST}/${x.solicitud.id}/cerrar-sin-plan`, { body: { motivo: motivo.value } });
      if (!r.ok) { show($("estMsg"), r.data.message || "No se pudo cerrar la solicitud."); return; }
      toast("Solicitud cerrada.");
      closePanel();
      loadList();
    }));
    return card;
  }

  function pagosHead(x) {
    const s = x.solicitud, head = el("div", "est-pagos-head");
    head.append(el("h3", null, "Pagos"));
    const f = el("div", "est-folio");
    f.append(el("span", null, "Folio de prórroga"), el("span", "est-chip", s.folio));
    const copy = el("button", "est-ico-btn");
    copy.type = "button";
    copy.title = "Copiar folio";
    copy.setAttribute("aria-label", "Copiar folio");
    copy.append(icon("tplCopy"));
    copy.addEventListener("click", async () => {
      try { await navigator.clipboard.writeText(s.folio); toast(`Folio ${s.folio} copiado.`); }
      catch (e) { toast("No se pudo copiar el folio."); }
    });
    f.append(copy);
    if (x.plan.editable && can(PLANES)) {   // sin pagos todavía: el plan se puede rehacer
      f.append(button("Modificar plan", "sec-btn sec-btn-ghost est-sm", () => { ui.modificando = true; paintTab(); }));
    }
    head.append(f);
    return head;
  }

  function pagoRow(q, n) {
    const r = el("div", "est-pago est-pago-" + q.estado);
    const a = el("div");
    a.append(el("b", null, pagoLabel(q.numero, n)), el("small", null, `Vence el ${fmtDate(q.fecha)}`));
    const estado = {
      pagada: `Pagado el ${fmtShort(q.pagado_el)}`, vencida: `Vencido · ${plural(diasDesde(q.fecha), "día")}`,
      parcial: `Abonado ${pesos(q.cubierto)}`, pendiente: "Pendiente",
    }[q.estado] || q.estado;
    r.append(a, el("span", "est-monto", pesos(q.monto)), el("span", "est-estado est-estado-" + q.estado, estado));
    if (q.pagado_el) {
      const rec = el("span", "est-rec");
      rec.title = "Folio del recibo de Caja";
      rec.append(icon("tplDoc"), el("span", null, q.recibo ? `Recibo ${q.recibo}` : "Pagado (Excel)"));
      r.append(rec);
    } else {
      const sr = el("span", "est-sinrec", "Sin recibo aún");
      sr.title = "Caja aún no registra este pago";
      r.append(sr);
    }
    return r;
  }

  function recibosCard(x) {
    const sec = card("Recibos de Caja");
    const ul = el("ul", "est-recibos");
    (x.recibos || []).forEach((r) => {
      const li = el("li", r.anulado ? "is-void" : "");
      li.append(el("b", null, r.folio || "Histórico"), el("span", null, fmtDate(r.fecha)), el("span", null, pesos(r.monto)));
      if (r.anulado) li.append(el("small", null, "Anulado: " + (r.motivo_anulacion || "")));
      ul.append(li);
    });
    sec.append(ul.children.length ? ul : el("p", "est-note", "Sin recibos."));
    return sec;
  }

  function sitRow(tipo, title, sub) {
    const r = el("div", "est-sit-row est-sit-" + tipo);
    const ico = el("span", "est-sit-ico");
    ico.append(icon({ ok: "tplOk", warn: "tplWarn", mail: "tplMail" }[tipo]));
    const t = el("div");
    t.append(el("b", null, title), el("small", null, sub));
    r.append(ico, t);
    return r;
  }

  function situacionCard(x) {
    const s = x.solicitud, c = x.cuenta, e = x.estudiante, bl = x.bloqueo || {}, rec = x.recordatorio || {};
    const venc = c.situacion === "atrasada", conSaldo = cents(c.saldo) > 0;
    const sec = card("Situación del alumno", "est-sit" + (venc ? " is-alert" : ""));
    if (bl.avisar_desbloqueo) sec.append(sitRow("warn", "Liquidó y sigue en la lista de adeudos", "Avisa el desbloqueo para sacarlo de la lista."));
    else if (bl.exportada && c.situacion !== "liquidada") sec.append(sitRow("warn", "Está en la lista de adeudos", `Se exportó el ${fmtDate(bl.exportada)}. Sale de la lista al pagar.`));
    else if (bl.avisado) sec.append(sitRow("ok", "Desbloqueo avisado", `El ${fmtDate(bl.avisado)}.`));
    else if (venc) sec.append(sitRow("warn", "Tiene un pago vencido", "Saldrá en la próxima lista de adeudos que se exporte."));
    else sec.append(sitRow("ok", "No está en la lista de adeudos", "No tiene pagos vencidos."));
    sec.append(rec.ultimo
      ? sitRow("mail", `Último recordatorio: ${fmtDateTime(rec.ultimo)}`, e.correo ? `Enviado a ${e.correo}` : "Aviso en la plataforma")
      : sitRow("mail", "Sin recordatorios enviados", "Aún no se le ha enviado ninguno."));

    const b = button(conSaldo ? "Enviar recordatorio" : "Sin saldo pendiente", "est-remind" + (venc ? " is-alert" : ""), async () => {
      show($("estMsg"), "");
      apply(await api(`${EST}/${s.id}/recordar`, { body: {} }), "Recordatorio enviado.");
    });
    b.prepend(icon("tplMail"));
    b.disabled = !rec.puede;
    if (can(REMIND)) sec.append(b);
    const hint = !conSaldo ? "El estudiante ya liquidó su adeudo."
      : !rec.puede ? (rec.ultimo ? "Ya se le envió uno en las últimas 24 horas." : "No tiene correo ni cuenta en la plataforma.")
        : venc ? "Tiene un pago vencido: conviene avisarle." : `Se envía a ${e.correo || "su cuenta en la plataforma"}`;
    sec.append(el("div", "est-hint" + (venc && rec.puede ? " is-alert" : ""), hint));
    if (x.carta && !x.carta.firmada && can(REMIND)) sec.append(button("Recordar firma", "sec-btn est-sm", async () => {
      show($("estMsg"), "");
      apply(await api(`${EST}/${s.id}/recordar-pendiente`, { body: { que: "firma" } }), "Recordatorio de firma enviado.");
    }));
    if (bl.avisar_desbloqueo && can("prorrogas_tec.students.api.export")) sec.append(button("Avisar desbloqueo", "sec-btn est-sm", async () => {
      show($("estMsg"), "");
      apply(await api(`${EST}/${s.id}/desbloqueo-avisado`, { body: {} }), "Desbloqueo avisado.");
    }));
    return sec;
  }

  // Enlace a la referencia bancaria del alumno, o aviso de que falta con botón para recordársela.
  function refNode(x) {
    const s = x.solicitud, box = el("span", "est-ref");
    if (s.referencia) {
      const a = el("a", "est-ver", "Ver referencia");
      a.href = `${API}${EST}/${s.id}/referencia.pdf`;
      a.target = "_blank";
      a.rel = "noopener";
      box.append(a);
    } else {
      box.append(el("span", null, "Sin referencia "), !can(REMIND) || x.cuenta.total !== null ? "" : button("Recordar referencia", "sec-btn est-sm", async () => {
        show($("estMsg"), "");
        apply(await api(`${EST}/${s.id}/recordar-pendiente`, { body: { que: "referencia" } }), "Recordatorio de referencia enviado.");
      }));
    }
    return box;
  }

  // Crear el plan o rehacerlo (solo sin pagos): el total se reparte en pagos iguales.
  // Un plan nuevo arranca con las fechas de Configuración; si una ya pasó queda vacía y la secretaria elige otra.
  function planForm(x) {
    const s = x.solicitud, c = x.cuenta, p = x.plan, mod = c.parcialidades.length > 0;
    const b = ui.borrador || (ui.borrador = mod
      ? { total: c.total, n: OPCIONES.includes(c.parcialidades.length) ? c.parcialidades.length : 1,
        fechas: c.parcialidades.map((q) => q.fecha), montos: null }
      : { total: "", n: OPCIONES.includes(s.plazos) ? s.plazos : 1,
        fechas: p.fechas_sugeridas.map((f) => (f >= todayIso() ? f : "")), montos: null });
    let seq = 0;
    let timer = null;

    const sec = card(null, "est-form");
    const top = el("div");
    top.append(el("h3", null, mod ? "Modificar plan de pagos" : "Crear plan de pagos"),
      el("div", "est-form-sub", "El total se divide en pagos iguales."));
    const grid = el("div", "est-form-grid");
    const left = el("div", "est-form-left");

    const money$ = el("div", "est-money");
    const total = input("text", { inputmode: "decimal", placeholder: "0.00", "aria-label": "Total del adeudo" });
    total.value = b.total;
    money$.append(el("span", null, "$"), total);
    const totalField = el("div", "est-field");
    totalField.append(el("span", null, "Total del adeudo"), money$, refNode(x));

    const opts = el("div", "est-opts");
    const optBtns = OPCIONES.map((v) => {
      const o = el("button", "est-opt");
      o.type = "button";
      const t = el("span", "est-opt-top");
      t.append(el("b", null, plural(v, "pago")));
      if (v === s.plazos) t.append(el("span", "est-opt-tag", "Solicitado"));
      o.append(t, el("small"));
      o.addEventListener("click", () => { b.n = v; b.montos = null; rows(); reparto(); });
      opts.append(o);
      return o;
    });
    const optField = el("div", "est-field");
    optField.append(el("span", null, "Número de pagos"), opts);
    left.append(totalField, optField);

    const prev = el("div", "est-prev");
    prev.append(el("div", "est-prev-title", "Vista previa"));
    const prevRows = el("div");
    const prevHint = el("div", "est-prev-hint", "Escribe el total para ver cuánto pagará en cada fecha.");
    prev.append(prevRows, prevHint);
    grid.append(left, prev);

    const foot = el("div", "est-form-foot");
    const note = el("div", "est-form-note");
    note.append(icon("tplInfo"), el("span", null, mod
      ? "Al estudiante le llega un correo con su nuevo plan y una carta nueva para firmar."
      : "Los recordatorios se activan cuando el plan esté creado."));
    const actions = el("div", "est-form-actions");
    if (mod) {
      const cancel = el("button", "sec-btn sec-btn-ghost", "Cancelar");
      cancel.type = "button";
      cancel.addEventListener("click", () => { ui.modificando = false; ui.borrador = null; paintTab(); });
      actions.append(cancel);
    }
    const ok = button("Confirmar plan", "est-confirm", async () => {
      show($("estMsg"), "");
      const r = await api(`${EST}/${s.id}/plan`, { body: {
        total: totalTxt(), parcialidades: b.montos.map((m, i) => ({ monto: m, fecha: b.fechas[i] })) } });
      if (r.ok) Object.assign(ui, { modificando: false, borrador: null });
      apply(r, mod ? "Plan modificado. Le avisamos al estudiante." : "Plan confirmado.");
    });
    actions.append(ok);
    foot.append(note, actions);
    sec.append(top, grid, foot);

    const totalTxt = () => { const t = cents(String(b.total).replace(/[$,\s]/g, "")); return t > 0 ? (t / 100).toFixed(2) : null; };
    const listo = () => !!b.montos && b.montos.length === b.n && Array.from({ length: b.n }, (_, i) => b.fechas[i]).every(Boolean);
    const paintOk = () => { ok.disabled = !listo(); };

    function paintOpts() {
      optBtns.forEach((o, i) => {
        const v = OPCIONES[i], f = b.fechas;
        o.setAttribute("aria-pressed", String(v === b.n));
        o.querySelector("small").textContent = v === 1
          ? "Una sola exhibición" + (f[0] ? ` · ${fmtShort(f[0])}` : "")
          : f[0] && f[1] ? `${fmtShort(f[0])} y ${fmtShort(f[1])}` : "Dos pagos iguales";
      });
      paintOk();
    }

    function rows() {
      paintOpts();
      prevRows.textContent = "";
      for (let i = 0; i < b.n; i++) {
        const r = el("div", "est-prev-row");
        const t = el("div");
        const d = input("date", { min: todayIso(), "aria-label": `Fecha límite del ${pagoLabel(i + 1, b.n).toLowerCase()}` });
        if (p.fecha_limite) d.max = p.fecha_limite;
        d.value = b.fechas[i] || "";
        d.addEventListener("change", () => { b.fechas[i] = d.value; paintOpts(); });
        const lab = el("label");
        lab.append(el("span", null, "Fecha límite:"), d);
        t.append(el("b", null, pagoLabel(i + 1, b.n)), lab);
        r.append(t, el("span", "est-monto" + (b.montos ? "" : " is-empty"), b.montos ? pesos(b.montos[i]) : "$ —"));
        prevRows.append(r);
      }
      prevHint.hidden = !!b.montos;
    }

    async function reparto() {
      const my = ++seq, t = totalTxt();
      if (!t) { b.montos = null; rows(); return; }
      const r = await api(`${EST}/reparto?total=${t}&n=${b.n}`);
      if (my !== seq) return;
      b.montos = r.ok ? r.data.montos : null;
      if (!r.ok) show($("estMsg"), r.data.message || "No se pudo repartir el total.");
      rows();
    }

    total.addEventListener("input", () => {
      b.total = total.value;
      b.montos = null;
      paintOk();
      clearTimeout(timer);
      timer = setTimeout(reparto, 300);
    });
    rows();
    if (totalTxt()) reparto();
    return sec;
  }

  // ── Solicitud y documentos ──────────────────────────────────────────
  function solPane(x) {
    const s = x.solicitud, e = x.estudiante, grid = el("div", "est-two");
    const datos = card("Datos de la solicitud");
    [["Folio de prórroga", s.folio], ["Solicitada", fmtDateTime(s.creada)], ["Aceptada", s.decidida ? fmtDateTime(s.decidida) : "—"],
      ["Pagos pedidos", s.plazos ?? "—"], ["Semestre", s.semestre], ["Correo", e.correo || "—"]].forEach(([k, v]) => {
      const r = el("div", "est-kv");
      r.append(el("span", null, k), el("span", null, String(v)));
      datos.append(r);
    });
    const rr = el("div", "est-kv");
    rr.append(el("span", null, "Referencia"), refNode(x));
    datos.append(rr);
    datos.append(el("div", "est-card-note", "El motivo viene en el Formato de solicitud."));

    const docs = card("Documentos");
    (s.documentos || []).forEach((d) => {
      const r = el("div", "est-doc");
      const ico = el("span", "est-doc-ico");
      ico.append(icon("tplDoc"));
      const t = el("div", "est-doc-txt");
      const sub = el("small", null, `Versión ${d.version}`);
      if (d.firmado) sub.append(el("span", "est-firmado", "Firmado"));
      else if (String(d.tipo).startsWith("carta_compromiso")) sub.append(el("span", "est-pend", "Firma pendiente"));
      t.append(el("b", null, d.label), sub);
      const a = el("a", "est-ver", "Ver / imprimir");
      a.href = `${API}/solicitudes/${s.id}/documentos/${d.id}.pdf`;
      a.target = "_blank";
      a.rel = "noopener";
      r.append(ico, t, a);
      docs.append(r);
    });
    if (!(s.documentos || []).length) docs.append(el("p", "est-note", "Sin documentos."));
    grid.append(datos, docs);
    return grid;
  }

  // ── Historial ───────────────────────────────────────────────────────
  function detalle(ev) {
    const d = ev.datos || {};
    const plan = () => plural((d.parcialidades || []).length, "pago") + ": "
      + (d.parcialidades || []).map((q) => `${pesos(q.monto)} el ${fmtDate(q.fecha)}`).join(" · ");
    switch (ev.tipo) {
      case "solicitud_creada": return [d.plazos ? plural(d.plazos, "pago") : null, d.periodo].filter(Boolean).join(" · ");
      case "solicitud_aceptada": return d.comentario ? `Comentario: “${d.comentario}”` : "Sin comentario";
      case "documento_generado": case "documento_firmado": return `${d.documento || d.doc_type} · versión ${d.version}`;
      case "plan_confirmado": case "plan_modificado": return plan();
      case "recibo_registrado": return `Recibo ${d.folio} · ${pesos(d.monto)} · pagado el ${fmtDate(d.fecha)}`;
      case "recibo_anulado": return `Recibo ${d.folio} · ${pesos(d.monto)} · ${d.motivo || ""}`;
      case "recordatorio_enviado": return d.saldo ? `Saldo de ${pesos(d.saldo)}` : "";
      case "recordatorio_pendiente": return d.que === "referencia" ? "Referencia bancaria" : "Firma de la carta";
      case "correo_no_enviado": return d.aviso ? `Aviso de ${AVISO[d.aviso] || d.aviso}` : "";
      default: return "";
    }
  }

  function histPane(x) {
    const ul = el("ul", "est-hist");
    (x.historial || []).forEach((ev) => {
      const li = el("li");
      const rail = el("span", "est-hist-rail");
      rail.append(el("span", "est-hd est-hd-" + (PUNTO[ev.tipo] || "gris")), el("span", "est-hist-line"));
      const t = el("div", "est-hist-txt");
      t.append(el("b", null, HIST[ev.tipo] || ev.tipo));
      const det = detalle(ev);
      if (det) t.append(el("small", null, det));
      const when = el("time", null, fmtDateTime(ev.fecha));
      when.dateTime = ev.fecha;
      li.append(rail, t, when);
      ul.append(li);
    });
    if (!ul.children.length) return el("p", "est-note", "Sin movimientos.");
    return ul;
  }

  loadPeriods();
})();
