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
    row.dataset.id = e.id;
    row.addEventListener("click", () => openPanel(e.id));
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

  // ── Modal: detalle, saldar y anular ─────────────────────────────────
  const perms = (document.body.dataset.perms || "").split(" ");
  const can = (p) => perms.includes("*") || perms.includes(p);
  const RECORD = "prorrogas_tec.payments.api.record";
  const VOID = "prorrogas_tec.payments.api.void";
  const dlg = $("cajDialog");
  const ui = { x: null, form: null, anul: null, notice: null, just: null };
  let openSeq = 0;

  const plural = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;
  const icon = (id) => $(id).content.firstElementChild.cloneNode(true);
  const pdf = (id, tail) => `${API}${CAJA}/${id}/${tail}`;

  function toast(msg) {
    const t = $("cajToast");
    t.textContent = msg;
    t.hidden = false;
    clearTimeout(toast.t);
    toast.t = setTimeout(() => { t.hidden = true; }, 3500);
  }

  function todayIso() {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  }

  // Deshabilita el botón mientras corre fn: el servidor ya protege el doble clic, la pantalla no lo invita.
  async function busy(btn, fn) {
    if (btn.disabled) return;
    btn.disabled = true;
    try { await fn(); } catch (e) { toast("Ocurrió un error inesperado."); } finally { btn.disabled = false; }
  }

  function button(text, cls, onClick) {
    const b = el("button", cls, text);
    b.type = "button";
    b.addEventListener("click", () => busy(b, () => onClick(b)));
    return b;
  }

  function link(text, href, cls) {
    const a = el("a", cls, text);
    a.href = href; a.target = "_blank"; a.rel = "noopener";
    return a;
  }

  async function openPanel(id) {
    const seq = ++openSeq;
    if (st.openId !== id) Object.assign(ui, { x: null, form: null, anul: null, notice: null, just: null });
    st.openId = id;
    if (!dlg.open) {
      ["cajNombre", "cajBadge", "cajControl", "cajCarrera", "cajSemestre", "cajFolio"].forEach((k) => { $(k).textContent = ""; });
      $("cajNombre").textContent = "Cargando…";
      $("cajBody").textContent = "";
      dlg.showModal();
    }
    await cargar(id, seq);
    loadList();   // marca la fila abierta
  }

  // Trae el detalle real; con seq viejo (otro alumno abierto o modal cerrado) no pinta nada.
  async function cargar(id, seq) {
    const r = await api(`${CAJA}/${id}`);
    if (seq !== openSeq) return false;
    if (!r.ok) {
      $("cajBody").textContent = "";
      $("cajBody").append(el("div", "est-error", r.data.message || "No se pudo cargar el detalle."));
      return false;
    }
    ui.x = r.data;
    paint();
    return true;
  }

  function closePanel() { if (dlg.open) dlg.close(); }
  dlg.addEventListener("close", () => {   // también con Esc
    const id = st.openId;
    openSeq += 1;
    st.openId = null;
    document.querySelectorAll(".caj-fila.is-open").forEach((n) => n.classList.remove("is-open"));
    const fila = document.querySelector(`.caj-fila[data-id="${id}"]`);
    if (fila) fila.focus();
  });
  $("cajCerrar").addEventListener("click", closePanel);
  dlg.addEventListener("click", (ev) => { if (ev.target === dlg) closePanel(); });
  $("cajCopiar").addEventListener("click", () => {
    const f = ui.x && ui.x.folio;
    if (!f) return;
    try { navigator.clipboard.writeText(f); } catch (e) { /* sin permiso de portapapeles: el aviso sale igual */ }
    toast(`Folio ${f} copiado`);
  });

  function notice(kind, text) {
    const n = el("div", "caj-notice " + (kind === "ok" ? "is-ok" : "is-anul"));
    n.setAttribute("role", "status");
    const ic = el("span", "caj-notice-ic");
    ic.append(icon("tplOk"));
    const x = el("button", "caj-notice-x");
    x.type = "button";
    x.setAttribute("aria-label", "Cerrar aviso");
    x.append(closeIcon());
    x.addEventListener("click", () => { ui.notice = null; paint(); });
    n.append(ic, el("span", "caj-notice-t", text), x);
    return n;
  }

  function closeIcon() {
    const s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    s.setAttribute("width", "14"); s.setAttribute("height", "14"); s.setAttribute("viewBox", "0 0 24 24");
    s.setAttribute("fill", "none"); s.setAttribute("stroke", "currentColor"); s.setAttribute("stroke-width", "2.2");
    s.setAttribute("stroke-linecap", "round"); s.setAttribute("aria-hidden", "true");
    const p = document.createElementNS("http://www.w3.org/2000/svg", "path");
    p.setAttribute("d", "M6 6l12 12M18 6L6 18");
    s.append(p);
    return s;
  }

  function paint() {
    const x = ui.x;
    if (!x) return;
    $("cajNombre").textContent = x.nombre;
    const [sit, tono] = SITUACION[x.situacion] || [x.situacion, "gris"];
    const badge = $("cajBadge");
    badge.textContent = sit;
    badge.className = "est-badge est-badge-" + tono;
    $("cajControl").textContent = x.control;
    $("cajCarrera").textContent = x.carrera;
    $("cajSemestre").textContent = x.semestre;
    $("cajFolio").textContent = x.folio;

    const body = $("cajBody");
    body.textContent = "";
    if (ui.notice) body.append(notice(ui.notice.kind, ui.notice.text));
    const pagos = x.pagos || [];
    if (!pagos.length) {
      const c = el("div", "caj-sinplan");
      const ic = el("span", "caj-sinplan-ic");
      ic.append(icon("tplCal"));
      const t = el("div");
      t.append(el("b", null, "Aún no se puede cobrar"),
        el("div", null, "Su prórroga está aceptada, pero Secretaría todavía no arma su plan de pagos. Pídele al alumno que regrese cuando el plan esté listo."));
      c.append(ic, t);
      body.append(c);
    } else {
      body.append(sums(x));
    }
    const cols = el("div", "caj-cols");
    if (pagos.length) {
      const col = el("div", "caj-pagos");
      col.append(el("h3", null, "Pagos"));
      const sig = pagos.find((p) => p.siguiente);
      pagos.forEach((p) => col.append(pagoCard(x, p, pagos.length, sig)));
      cols.append(col);
    }
    cols.append(referencia(x));
    body.append(cols);
  }

  function sums(x) {
    const box = el("div", "caj-sums");
    [["Total", x.total, ""], ["Pagado", x.pagado, ""], ["Saldo", x.saldo, "saldo"]].forEach(([label, v, k]) => {
      const c = el("div", "caj-sum");
      const val = el("div", "caj-sum-v" + (k ? " is-saldo" : ""), v == null ? "—" : pesos(v));
      if (k) val.style.color = x.situacion === "atrasada" ? "var(--alert)" : cents(v) === 0 ? "var(--wine)" : "var(--ink)";
      c.append(el("div", "caj-sum-l", label), val);
      box.append(c);
    });
    return box;
  }

  function referencia(x) {
    const c = el("div", "caj-ref");
    c.append(el("h3", null, "Referencia bancaria"));
    if (x.referencia) {
      const a = link("Abrir PDF", pdf(x.id, "referencia.pdf"), "caj-ref-btn");
      a.prepend(icon("tplDocTxt"));
      c.append(a, el("div", "caj-ref-nota", "La subió el alumno. Solo lectura."));
    } else {
      c.append(el("div", "caj-ref-vacia", "Sin referencia"), el("div", "caj-ref-nota", "El alumno aún no la sube."));
    }
    return c;
  }

  function pagoCard(x, p, n, sig) {
    const paid = p.estado === "pagada", venc = p.estado === "vencida";
    const label = `Pago ${p.numero}/${n}`;
    const card = el("div", "caj-pago" + (paid ? " is-paid" : "") + (venc ? " is-venc" : "") + (p.siguiente ? " is-next" : "")
      + (ui.just === p.numero ? " is-just" : ""));
    const head = el("div", "caj-pago-head");
    const t = el("div", "caj-pago-t");
    const lim = el("div", "caj-pago-lim", "Fecha límite ");
    lim.append(el("span", null, fmtDate(p.fecha)));
    t.append(el("b", null, label), lim);
    const [pill, tono] = paid ? ["Pagado", "paid"] : venc ? [`Vencido · ${plural(p.dias_vencido, "día")}`, "venc"] : ["Pendiente", "pend"];
    head.append(t, el("span", "caj-pago-m", pesos(paid ? p.monto : p.a_cobrar)), el("span", "caj-pill is-" + tono, pill));
    card.append(head);

    if (paid) {
      const r = p.recibo || {};
      const row = el("div", "caj-paid");
      const f = el("span", "caj-paid-f", "Folio de Caja ");
      f.append(el("b", null, r.folio || "Histórico"), document.createTextNode(" · "), el("span", null, fmtDate(r.fecha)));
      const scan = el("span", "caj-scan" + (p.recibo_subido ? "" : " is-falta"));
      scan.append(el("i", "caj-dot"), document.createTextNode(p.recibo_subido ? `Recibo subido el ${fmtDate(p.recibo_subido)}` : "Falta subir recibo"));
      row.append(f, scan, el("span", "caj-grow"));
      if (p.anulable && can(VOID) && !ui.form && !ui.anul) {
        const b = button("Anular", "caj-anular-btn", async () => {
          Object.assign(ui, { anul: { numero: p.numero, motivo: "", err: "" }, notice: null, just: null });
          paint();
          const ta = document.querySelector(".caj-anul textarea");
          if (ta) ta.focus();
        });
        row.append(b);
      }
      card.append(row);
    } else if (p.siguiente) {
      if (!ui.form && can(RECORD)) {
        const row = el("div", "caj-saldar-row");
        row.append(el("span", venc ? "caj-nota is-venc" : "caj-nota", venc ? "Se cobra igual, sin recargo." : ""));
        row.append(button("Saldar pago", "caj-saldar-btn", async () => {
          Object.assign(ui, { form: { numero: p.numero, folio: "", fecha: todayIso(), fErr: "", dErr: "" }, notice: null, just: null });
          paint();
          const i = document.querySelector(".caj-form input");
          if (i) i.focus();
        }));
        card.append(row);
      }
    } else if (sig) {
      card.append(el("div", "caj-later", `Se cobra después de Pago ${sig.numero}/${n}.`));
    }

    if (!paid && p.recibo_subido) {
      const s = el("div", "caj-scan-pend", `El alumno ya subió un recibo el ${fmtDate(p.recibo_subido)}. `);
      s.append(link("Ver recibo", pdf(x.id, `parcialidades/${p.numero}/recibo.pdf`), "caj-lnk"));
      card.append(s);
    }
    if (ui.form && ui.form.numero === p.numero && p.siguiente) card.append(saldarForm(x, p, label));
    if (ui.anul && ui.anul.numero === p.numero && p.anulable) card.append(anularForm(x, p, label));
    return card;
  }

  function fieldErr(node, msg) {
    const e = el("span", "cfg-err", msg);
    e.hidden = !msg;
    node.append(e);
    return e;
  }

  function saldarForm(x, p, label) {
    const f = ui.form;
    const box = el("div", "caj-form");
    box.append(el("b", "caj-form-t", `Saldar ${label}`));
    const grid = el("div", "caj-form-grid");

    const m = el("div", "caj-field-f");
    m.append(el("span", "caj-lbl", "Monto"));
    const lock = el("span", "caj-lock");
    lock.append(el("span", null, pesos(p.a_cobrar)), icon("tplLock"));
    m.append(lock, el("span", "cfg-hint", "Pago completo, sin abonos."));

    const lf = el("label", "caj-field-f" + (f.fErr ? " has-err" : ""), "Folio del recibo de Caja");
    const inp = el("input");
    inp.value = f.folio; inp.placeholder = "Ej. C-10302"; inp.maxLength = 40; inp.autocomplete = "off";
    inp.setAttribute("aria-invalid", String(!!f.fErr));
    inp.addEventListener("input", () => { f.folio = inp.value; f.fErr = ""; });
    lf.append(inp);
    fieldErr(lf, f.fErr);

    const ld = el("label", "caj-field-f cfg-field" + (f.dErr ? " has-err" : ""), "Fecha de pago");
    const box2 = el("span", "cfg-date");
    const txt = el("span", "cfg-date-txt" + (f.fecha ? "" : " is-vacio"), f.fecha ? fmtDate(f.fecha) : "Elige una fecha");
    const di = el("input");
    di.type = "date"; di.value = f.fecha; di.max = todayIso();
    di.setAttribute("aria-invalid", String(!!f.dErr));
    const hint = el("span", "cfg-hint", f.fecha === todayIso() ? "Hoy" : "No puede ser una fecha futura.");
    const derr = el("span", "cfg-err", f.dErr);
    derr.hidden = !f.dErr;
    di.addEventListener("change", () => {
      f.fecha = di.value; f.dErr = "";
      txt.textContent = f.fecha ? fmtDate(f.fecha) : "Elige una fecha";
      txt.classList.toggle("is-vacio", !f.fecha);
      hint.textContent = f.fecha === todayIso() ? "Hoy" : "No puede ser una fecha futura.";
      derr.hidden = true; ld.classList.remove("has-err"); di.setAttribute("aria-invalid", "false");
    });
    box2.append(txt, icon("tplCal"), di);
    ld.append(box2, derr, hint);
    grid.append(m, lf, ld);

    const acts = el("div", "caj-confirm");
    const cancel = el("button", "sec-btn sec-btn-ghost", "Cancelar");
    cancel.type = "button";
    cancel.addEventListener("click", () => { ui.form = null; paint(); });
    acts.append(cancel, button("Confirmar pago", "sec-btn", (b) => confirmarPago(x, p, label)));
    box.append(grid, acts);
    return box;
  }

  async function confirmarPago(x, p, label) {
    const f = ui.form;
    const folio = f.folio.trim(), hoy = todayIso();
    f.fErr = folio ? "" : "Captura el folio del recibo de Caja.";
    f.dErr = !f.fecha ? "Elige la fecha de pago." : f.fecha > hoy ? "La fecha no puede ser futura." : "";
    if (f.fErr || f.dErr) { paint(); focoError(".caj-form"); return; }
    const seq = openSeq;
    const r = await api(`${CAJA}/${x.id}/saldar`, { body: { numero: p.numero, folio, fecha: f.fecha } });
    if (seq !== openSeq) return;
    if (r.ok) {
      const rec = (r.data.pagos.find((q) => q.numero === p.numero) || {}).recibo || {};
      Object.assign(ui, { form: null, just: p.numero, x: r.data,
        notice: { kind: "ok", text: `${label} saldado con el folio ${rec.folio || folio}.` + (r.data.situacion === "liquidada" ? " La prórroga quedó liquidada." : "") } });
      paint();
      loadList();
      return;
    }
    const code = r.data.error, msg = r.data.message || "No se pudo registrar el pago.";
    if (code === "folio_duplicado" || code === "folio_invalido") f.fErr = msg;
    else if (code === "fecha_invalida") f.dErr = msg;
    else { await recargar(msg); return; }
    paint();
    focoError(".caj-form");
  }

  function anularForm(x, p, label) {
    const a = ui.anul;
    const r = p.recibo || {};
    const box = el("div", "caj-anul");
    const t = el("b", "caj-anul-t", "Anular recibo ");
    t.append(el("span", null, r.folio || "Histórico"));
    box.append(t);
    box.append(el("div", "caj-anul-d", `${label} vuelve a quedar sin cubrir y se podrá saldar de nuevo.` +
      (p.recibo_subido ? " El recibo que subió el alumno se conserva: sirve para verificar el folio correcto." : "")));
    if (p.recibo_subido) {
      const l = link("Ver recibo del alumno para comparar", pdf(x.id, `parcialidades/${p.numero}/recibo.pdf`), "caj-anul-ok");
      l.prepend(icon("tplDoc"));
      box.append(l);
    }
    const lab = el("label", "caj-field-f" + (a.err ? " has-err" : ""), "Motivo de la anulación");
    const ta = el("textarea");
    ta.rows = 2; ta.placeholder = "Ej. Se capturó mal el folio"; ta.value = a.motivo; ta.maxLength = 500;
    ta.setAttribute("aria-invalid", String(!!a.err));
    ta.addEventListener("input", () => { a.motivo = ta.value; a.err = ""; });
    lab.append(ta);
    fieldErr(lab, a.err);
    const acts = el("div", "caj-confirm");
    const cancel = el("button", "sec-btn sec-btn-ghost", "Cancelar");
    cancel.type = "button";
    cancel.addEventListener("click", () => { ui.anul = null; paint(); });
    acts.append(cancel, button("Anular recibo", "sec-btn caj-btn-anul", () => confirmarAnular(x, p, label)));
    box.append(lab, acts);
    return box;
  }

  async function confirmarAnular(x, p, label) {
    const a = ui.anul;
    const motivo = a.motivo.trim();
    if (!motivo) { a.err = "Escribe el motivo de la anulación."; paint(); focoError(".caj-anul"); return; }
    const seq = openSeq;
    const r = await api(`${CAJA}/${x.id}/recibos/${p.recibo.id}/anular`, { body: { motivo } });
    if (seq !== openSeq) return;
    if (r.ok) {
      Object.assign(ui, { anul: null, just: null, x: r.data,
        notice: { kind: "anul", text: `Recibo ${p.recibo.folio || "Histórico"} anulado. ${label} vuelve a estar ${p.estado === "vencida" ? "vencido" : "pendiente"}.` } });
      paint();
      loadList();
      return;
    }
    if (r.data.error === "motivo_requerido") { a.err = r.data.message || "Escribe el motivo de la anulación."; paint(); focoError(".caj-anul"); return; }
    await recargar(r.data.message || "No se pudo anular el recibo.");   // no_es_el_ultimo, ya_anulado…
  }

  // Cualquier otro rechazo: Caja ve el estado real y el motivo en el aviso.
  async function recargar(msg) {
    Object.assign(ui, { form: null, anul: null, just: null, notice: { kind: "anul", text: msg } });
    const seq = openSeq;
    if (await cargar(ui.x.id, seq)) loadList();
  }

  function focoError(scope) {
    const n = document.querySelector(`${scope} [aria-invalid="true"]`);
    if (n) n.focus();
  }

  loadSemestres();
  loadList();
})();
