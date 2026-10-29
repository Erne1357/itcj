// Prórrogas · QR y solicitudes (vista de secretaría).
// QR rotativo o invitación manual, tabla de pendientes y modal de revisión.
// APIs: /api/prorrogas/v2/{invitaciones,solicitudes,programs}. Todo texto del servidor entra con textContent.
(function () {
  "use strict";

  const root = document.querySelector(".sol");
  if (!root) return;
  const API = root.dataset.api;
  const $ = (id) => document.getElementById(id);
  const MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];

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

  function fmtDate(iso) {
    const d = new Date(iso);
    return `${d.getDate()} ${MESES[d.getMonth()]} ${d.getFullYear()}`;
  }

  // ── Modo del panel ──────────────────────────────────────────────────
  function setMode(qr) {
    $("modeQr").classList.toggle("is-active", qr);
    $("modeMan").classList.toggle("is-active", !qr);
    $("modeQr").setAttribute("aria-selected", String(qr));
    $("modeMan").setAttribute("aria-selected", String(!qr));
    $("paneQr").hidden = !qr;
    $("paneMan").hidden = qr;
  }
  $("modeQr").addEventListener("click", () => setMode(true));
  $("modeMan").addEventListener("click", () => { setMode(false); loadPrograms(); });

  // ── QR ──────────────────────────────────────────────────────────────
  let qrExpires = 0;
  let qrTimer = null;
  let qrBusy = false;

  function drawQr(link) {
    const box = $("qrBox");
    box.textContent = "";
    if (typeof qrcode === "undefined") {   // sin la librería, el enlace en texto sigue sirviendo
      box.append(el("code", "sol-qr-link", link));
      return;
    }
    const q = qrcode(0, "M");
    q.addData(link);
    q.make();
    box.innerHTML = q.createSvgTag({ cellSize: 6, margin: 0, scalable: true }); // SVG generado por la librería, sin datos del servidor
    const svg = box.querySelector("svg");
    if (svg) svg.setAttribute("aria-label", "Código QR para unirse");
  }

  function tick() {
    const left = Math.max(0, Math.round((qrExpires - Date.now()) / 1000));
    $("qrTimer").textContent = `${String(Math.floor(left / 60)).padStart(2, "0")}:${String(left % 60).padStart(2, "0")}`;
    if (left === 0) regenQr();
  }

  async function regenQr() {
    if (qrBusy) return;
    qrBusy = true;
    clearInterval(qrTimer);
    const r = await api("/invitaciones/qr", { method: "POST", body: {} });
    qrBusy = false;
    if (!r.ok) {
      show($("qrError"), r.data.message || "No se pudo generar el código.");
      return;
    }
    show($("qrError"), "");
    qrExpires = new Date(r.data.expires_at).getTime();
    drawQr(location.origin + r.data.path);
    tick();
    qrTimer = setInterval(tick, 1000);
  }
  $("qrRegen").addEventListener("click", regenQr);
  // Pestaña oculta: se detiene el contador; al volver se regenera si ya venció.
  document.addEventListener("visibilitychange", function () {
    if (document.hidden) { clearInterval(qrTimer); return; }
    if (qrExpires) { tick(); if (Date.now() < qrExpires) qrTimer = setInterval(tick, 1000); }
  });

  // ── Resumen del día ─────────────────────────────────────────────────
  async function loadToday() {
    const r = await api("/invitaciones/hoy");
    if (!r.ok) return;
    $("cntJoin").textContent = r.data.se_unieron_hoy;
    $("cntInv").textContent = r.data.invitaciones_hoy;
    const ul = $("invLast");
    ul.textContent = "";
    (r.data.ultimas || []).forEach((i) => {
      const li = el("li");
      li.append(el("span", null, i.correo), el("span", null, i.hora));
      ul.append(li);
    });
  }

  // ── Invitación manual ───────────────────────────────────────────────
  let programsLoaded = false;
  async function loadPrograms() {
    if (programsLoaded) return;
    const r = await api("/programs?limit=500");
    if (!r.ok) return;
    programsLoaded = true;
    (r.data.items || []).forEach((p) => {
      const o = el("option", null, p.name);
      o.value = p.id;
      $("invCarrera").append(o);
    });
  }

  let lookedUp = null;
  async function lookup() {
    const control = $("invControl").value.trim();
    lookedUp = null;
    $("invExtra").hidden = true;
    show($("invFound"), "");
    show($("invError"), "");
    if (!control) return;
    const r = await api(`/invitaciones/alumno?control=${encodeURIComponent(control)}`);
    if (!r.ok) { show($("invError"), r.data.message || "No se pudo buscar el número de control."); return; }
    lookedUp = r.data;
    $("invControl").value = r.data.control_number;
    $("invExtra").hidden = false;
    $("invDatos").hidden = !r.data.requiere_datos;
    $("invCorreo").value = r.data.correo_sugerido || "";
    show($("invFound"), r.data.existe ? `Cuenta existente: ${r.data.nombre}` : "No hay cuenta con ese número: captura sus datos.");
  }
  $("invControl").addEventListener("change", lookup);

  $("paneMan").addEventListener("submit", async function (e) {
    e.preventDefault();
    show($("invError"), "");
    if (!lookedUp || lookedUp.control_number !== $("invControl").value.trim().toUpperCase()) await lookup();
    if (!lookedUp) return;
    const body = { control_number: lookedUp.control_number, correo: $("invCorreo").value.trim() || null };
    if (lookedUp.requiere_datos) {
      body.nombres = $("invNombres").value;
      body.apellido_paterno = $("invPaterno").value;
      body.apellido_materno = $("invMaterno").value || null;
      body.program_id = parseInt($("invCarrera").value, 10) || null;
    }
    $("invSend").disabled = true;
    const r = await api("/invitaciones", { body });
    $("invSend").disabled = false;
    if (!r.ok) { show($("invError"), r.data.message || "No se pudo enviar la invitación."); return; }
    toast(`Invitación enviada a ${r.data.correo}`);
    $("paneMan").reset();
    $("invExtra").hidden = true;
    show($("invFound"), "");
    lookedUp = null;
    loadToday();
  });

  // ── Pendientes ──────────────────────────────────────────────────────
  let items = [];

  function renderRows() {
    const box = $("pendRows");
    box.textContent = "";
    $("pendCount").textContent = items.length;
    $("pendEmpty").hidden = items.length > 0;
    items.forEach((s) => {
      const row = el("div", "sol-row sol-row-item");
      row.tabIndex = 0;
      const who = el("div");
      who.append(el("div", "sol-name", s.nombre), el("div", "sol-ctrl", s.control));
      row.append(who, el("span", "sol-mail", s.correo), el("span", null, fmtDate(s.recibida)),
        el("span", "mono", String(s.plazos)), el("span", "sol-eye", "Revisar"));
      row.addEventListener("click", () => openReview(s));
      row.addEventListener("keydown", (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); openReview(s); } });
      box.append(row);
    });
  }

  async function loadPending() {
    const r = await api("/solicitudes");
    show($("pendError"), r.ok ? "" : (r.data.message || "No se pudieron cargar las solicitudes."));
    if (!r.ok) return;
    items = r.data.items || [];
    renderRows();
  }

  // ── Modal de revisión ───────────────────────────────────────────────
  const dlg = $("revDialog");
  let current = null;
  let deciding = false;

  function setBusy(b) {
    deciding = b;
    $("revReject").disabled = b;
    $("revAccept").disabled = b;
  }

  function openReview(s) {
    current = s;
    setBusy(false);
    $("revNombre").textContent = s.nombre;
    $("revFolio").textContent = s.folio;
    $("revControl").textContent = s.control;
    $("revCorreo").textContent = s.correo;
    $("revFecha").textContent = fmtDate(s.recibida);
    $("revPlazos").textContent = s.plazos;
    $("revArchivo").textContent = `solicitud_prorroga_${s.control}.pdf`;
    $("revComentario").value = "";
    show($("revError"), "");
    const pdf = $("revPdf");
    if (s.documento_id) {
      show($("revPdfMsg"), "");
      pdf.hidden = false;
      pdf.src = `${API}/solicitudes/${s.id}/documentos/${s.documento_id}.pdf`;
    } else {
      pdf.hidden = true;
      pdf.removeAttribute("src");
      show($("revPdfMsg"), "Esta solicitud no tiene PDF disponible.");
    }
    dlg.showModal();
  }

  function closeReview() {
    if (deciding) return;
    dlg.close();
  }
  dlg.addEventListener("close", () => { $("revPdf").removeAttribute("src"); current = null; });
  dlg.addEventListener("cancel", (e) => { if (deciding) e.preventDefault(); });
  $("revClose").addEventListener("click", closeReview);
  dlg.addEventListener("click", (e) => { if (e.target === dlg) closeReview(); });

  async function decide(aceptar) {
    if (!current || deciding) return;
    const comentario = $("revComentario").value.trim();
    if (!aceptar && !comentario) { show($("revError"), "Escribe el motivo del rechazo."); return; }
    show($("revError"), "");
    setBusy(true);
    const s = current;
    const r = await api(`/solicitudes/${s.id}/decision`, { body: { aceptar, comentario } });
    if (r.ok || r.status === 409) {   // 409 ya_resuelta: otra secretaria la decidió; también sale de la lista
      deciding = false;
      dlg.close();
      items = items.filter((x) => x.id !== s.id);
      renderRows();
      toast(r.ok ? (aceptar ? `Prórroga aceptada: ${s.folio}` : `Solicitud rechazada: ${s.folio}`)
                 : (r.data.message || "La solicitud ya fue resuelta."));
      return;
    }
    setBusy(false);
    show($("revError"), r.data.message || "No se pudo guardar la decisión.");
  }
  $("revAccept").addEventListener("click", () => decide(true));
  $("revReject").addEventListener("click", () => decide(false));

  regenQr();
  loadToday();
  loadPending();
})();
