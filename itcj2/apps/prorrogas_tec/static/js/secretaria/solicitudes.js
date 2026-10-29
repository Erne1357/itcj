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
  let qrExpires = 0;   // en el reloj del navegador: Date.now() + ttl del servidor
  let qrTimer = null;
  let qrBusy = false;
  let qrIssued = 0;    // última emisión; frena un ciclo de regeneraciones si el reloj o el ttl fallan
  const QR_MIN_GAP = 5000;

  function armQr() { clearInterval(qrTimer); qrTimer = setInterval(tick, 1000); }

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
    if (left === 0 && Date.now() - qrIssued >= QR_MIN_GAP) regenQr();
  }

  async function regenQr() {
    if (qrBusy) return;
    qrBusy = true;
    clearInterval(qrTimer);
    const r = await api("/invitaciones/qr", { method: "POST", body: {} });
    qrBusy = false;
    qrIssued = Date.now();
    if (!r.ok) {
      show($("qrError"), r.data.message || "No se pudo generar el código.");
      return;
    }
    show($("qrError"), "");
    qrExpires = Date.now() + r.data.ttl * 1000;   // nunca contra expires_at: es hora del servidor sin zona
    drawQr(location.origin + r.data.path);
    tick();
    armQr();
  }
  $("qrRegen").addEventListener("click", regenQr);

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
    $("paneMan").reset();
    $("invExtra").hidden = true;
    show($("invFound"), "");
    lookedUp = null;
    // Sin buzón la invitación no llega a nadie: no tiene aviso en la plataforma.
    if (r.data.enviado) toast(`Invitación enviada a ${r.data.correo}`);
    else show($("invError"), "La invitación quedó registrada pero el correo no salió. Revisa la conexión del correo en /itcj/config/email.");
    loadToday();
  });

  // ── Pendientes ──────────────────────────────────────────────────────
  let items = null;   // null hasta la primera carga, para que esa siempre pinte (aunque venga vacía)

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
    const next = r.data.items || [];
    if (JSON.stringify(next) === JSON.stringify(items)) return;   // sin cambios: no rehacer filas (ni perder el foco)
    items = next;
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

  // ── Refresco y pestaña oculta ───────────────────────────────────────
  let listTimer = null;
  function refresh() {
    loadToday();
    if (!dlg.open) loadPending();   // con el modal abierto no se toca la tabla; entra en el siguiente ciclo
  }
  function armRefresh() { clearInterval(listTimer); listTimer = setInterval(refresh, 20000); }

  // Oculta: se detienen el contador y el refresco. Al volver: se regenera el QR si venció y se refresca la lista.
  document.addEventListener("visibilitychange", function () {
    if (document.hidden) { clearInterval(qrTimer); clearInterval(listTimer); return; }
    if (qrExpires) { tick(); armQr(); }   // si venció, tick() regenera; el intervalo reintenta si el freno lo detuvo
    refresh();
    armRefresh();
  });

  regenQr();
  loadToday();
  loadPending();
  armRefresh();
})();
