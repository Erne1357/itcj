(function () {
  const API = "/api/prorrogas/v2/estudiante";
  const root = document.getElementById("mp-root");

  function el(tag, text, cls) {
    const e = document.createElement(tag);
    if (text != null) e.textContent = text;
    if (cls) e.className = cls;
    return e;
  }
  const plantilla = (id) => document.getElementById(id).content.firstElementChild.cloneNode(true);
  const icono = (n) => document.getElementById("mp-iconos").content.querySelector(`[data-i="${n}"]`).cloneNode(true);

  function tarjeta(...hijos) {
    const s = el("section", null, "card");
    s.append(...hijos);
    return s;
  }

  function mensaje(texto, cls) {
    root.replaceChildren(tarjeta(el("p", texto, cls || "lead")));
  }

  async function cancelar(id, btn) {
    if (!confirm("¿Cancelar esta solicitud? Ya no podrás pedir otra este semestre.")) return;
    btn.disabled = true;
    try {
      const r = await fetch(`${API}/solicitudes/${id}/cancelar`, { method: "POST", credentials: "include" });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        alert(d.message || "No se pudo cancelar.");
      }
    } catch (e) {
      alert("No se pudo cancelar.");
    }
    cargar();
  }

  // [insignia, clase de la insignia, título]
  const ESTADO = {
    pendiente: ["Pendiente", "t-warn", "Tu solicitud está en revisión"],
    aceptada: ["Aceptada", "t-ok", "¡Tu prórroga fue aceptada!"],
    rechazada: ["Rechazada", "t-bad", "Tu solicitud no fue aceptada"],
    cancelada: ["Cancelada", "t-neutral", "Cancelaste esta solicitud"],
  };
  const PARCIALIDAD = { pagada: ["Pagada", "t-ok"], parcial: ["Parcial", "t-warn"], pendiente: ["Pendiente", "t-neutral"], vencida: ["Vencida", "t-bad"] };

  function fecha(iso) {
    const [y, m, d] = String(iso).split("-");
    return d && m && y ? `${d}/${m}/${y}` : String(iso);
  }
  // "3650.00" -> "$3,650.00" sobre la cadena (sin float); con 2 decimales la regla no toca la parte decimal.
  const dinero = (v) => "$" + String(v).replace(/\B(?=(\d{3})+(?!\d))/g, ",");

  function encabezado(etiqueta, insignia, cls) {
    const row = el("div", null, "row");
    row.append(el("p", etiqueta, "label"), el("span", insignia, "badge " + cls));
    return row;
  }

  function datos(s) {
    const dl = el("dl", null, "kv");
    [["Folio", s.folio, "mono"], ["Periodo", s.semestre || "—"], ["Pagos", s.plazos != null ? String(s.plazos) : "—"]]
      .forEach(function ([k, v, cls]) {
        const d = el("div");
        d.append(el("dt", k), el("dd", v, cls));
        dl.append(d);
      });
    return dl;
  }

  function resumenAceptada(s) {
    const c = s.cuenta, p = el("p", null, "lead");
    if (s.por_firmar) p.append("Te falta ", el("strong", "un paso"), ": firmar tu carta compromiso.");
    else if (c.total === null) p.textContent = "La secretaria armará tu plan de pagos con base en tu referencia bancaria. Te avisaremos cuando esté listo.";
    else if (c.situacion === "liquidada") p.textContent = "Ya liquidaste tu prórroga.";
    else p.textContent = "Paga en las fechas de tu plan.";
    return p;
  }

  function planDePagos(c) {
    const izq = el("div"), der = el("p", null, "hint"), saldo = el("div", null, "saldo");
    izq.append(el("p", "Te falta pagar", "label"), el("p", dinero(c.saldo), "big"));
    der.append("Pagado " + dinero(c.pagado), el("br"), "de " + dinero(c.total));
    saldo.append(izq, der);

    const parcs = c.parcialidades || [];
    const prog = el("div", null, "prog"), barra = el("span");
    prog.setAttribute("role", "img");
    prog.setAttribute("aria-label", `Pagado ${parcs.filter((p) => p.estado === "pagada").length} de ${parcs.length} pagos`);
    const total = parseFloat(c.total);   // solo para el ancho de la barra
    barra.style.width = total > 0 ? Math.min(100, parseFloat(c.pagado) / total * 100) + "%" : "0%";
    prog.append(barra);

    const ol = el("ol", null, "pays"), sigue = c.proxima ? c.proxima.numero : null;
    parcs.forEach(function (p) {
      const pagada = p.estado === "pagada", esSigue = !pagada && p.numero === sigue;
      const li = el("li", null, "pay" + (pagada ? " done" : esSigue ? " next" : ""));
      const n = el("span", pagada ? null : String(p.numero), "pay-n");
      if (pagada) n.append(icono("check"));
      let detalle = `Pago ${p.numero} · ${pagada ? "" : "antes del "}${fecha(p.fecha)}`;
      if (p.estado === "parcial") detalle += ` · ${dinero(p.cubierto)} cubierto`;
      const main = el("div", null, "pay-main");
      main.append(el("strong", dinero(p.monto)), el("span", detalle, "hint"));
      const [txt, cls] = esSigue && p.estado === "pendiente" ? ["Sigue", "t-warn"] : PARCIALIDAD[p.estado] || [p.estado, "t-neutral"];
      li.append(n, main, el("span", txt, "badge " + cls));
      ol.append(li);
    });
    return tarjeta(el("h2", "Tu plan de pagos", "h2"), saldo, prog, ol);
  }

  function recibos(lista) {
    const sec = tarjeta(el("h2", "Recibos registrados", "h2"));
    if (!lista.length) {
      sec.append(el("p", "Aún no hay recibos registrados.", "hint"));
      return sec;
    }
    const ul = el("ul", null, "recs");
    lista.forEach(function (r) {
      const ico = el("span", null, "ico-circle t-ok"), det = el("span", null, "hint"), main = el("div", null, "rec-main");
      ico.append(icono("recibo"));
      det.append(el("span", r.folio || "Registro histórico", "mono"), " · " + fecha(r.fecha));
      main.append(el("strong", dinero(r.monto)), det);
      const li = el("li", null, "rec");
      li.append(ico, main);
      ul.append(li);
    });
    sec.append(ul);
    return sec;
  }

  function documentos(s) {
    const ul = el("ul", null, "docs");
    s.documentos.forEach(function (d) {
      const a = el("a");
      a.href = `${API}/solicitudes/${s.id}/documentos/${d.id}.pdf`;
      a.target = "_blank";
      a.rel = "noopener";
      a.append(icono("doc"), el("span", d.label + (d.firmado ? " (firmado)" : "")), icono("chev"));
      const li = el("li");
      li.append(a);
      ul.append(li);
    });
    return tarjeta(el("h2", "Tus documentos", "h2"), ul);
  }

  function seccionFirma(s) {
    const sec = plantilla("mp-firma-tpl");
    const q = (c) => sec.querySelector(c);
    const canvas = q("canvas"), btn = q(".mp-firmar"), acepto = q(".mp-acepto"), err = q(".mp-error");
    q(".mp-pdf").href = `${API}/solicitudes/${s.id}/documentos/${s.por_firmar}.pdf`;
    let firma = null, enviando = false;
    const actualizar = () => { btn.disabled = enviando || !(firma && !firma.vacia() && acepto.checked); };
    q(".mp-borrar").addEventListener("click", function () { firma.limpiar(); });
    acepto.addEventListener("change", actualizar);
    btn.addEventListener("click", async function () {
      if (btn.disabled) return;
      enviando = true;
      err.hidden = true;
      actualizar();
      try {
        const r = await fetch(`${API}/solicitudes/${s.id}/documentos/${s.por_firmar}/firmar`, {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ firma: firma.dataURL() }),
        });
        if (r.ok) { cargar(); return; }
        const d = await r.json().catch(() => ({}));
        if (r.status === 409) {   // documento_no_vigente / ya_firmado: avisar y mostrar el estado actual
          alert(d.message || "Este documento ya no se puede firmar.");
          cargar();
          return;
        }
        err.textContent = d.message || "No se pudo firmar el documento.";
      } catch (e) {
        err.textContent = "No se pudo firmar el documento.";
      } finally {
        enviando = false;
        actualizar();
      }
      err.hidden = false;
    });
    // El lienzo se crea al estar en el documento: necesita su ancho real.
    sec.crear = function () { firma = Firma.crear(canvas, actualizar); };
    return sec;
  }

  function seccionReferencia(s) {
    const url = `${API}/solicitudes/${s.id}/referencia.pdf`;
    if (s.referencia) {
      const a = el("a", "Ver mi referencia", "btn-text");
      a.href = url;
      a.target = "_blank";
      a.rel = "noopener";
      return tarjeta(el("p", "Referencia subida el " + fecha(s.referencia.slice(0, 10)), "lead"), a);
    }
    const inp = el("input", null, "input"), btn = el("button", "Subir referencia", "btn"), err = el("p", null, "error");
    inp.type = "file";
    inp.accept = "application/pdf";
    btn.type = "button";
    err.hidden = true;
    btn.addEventListener("click", async function () {
      if (!inp.files[0]) { err.textContent = "Elige tu PDF."; err.hidden = false; return; }
      btn.disabled = true;
      err.hidden = true;
      const fd = new FormData();
      fd.append("archivo", inp.files[0]);
      try {
        const r = await fetch(`${API}/solicitudes/${s.id}/referencia`, { method: "POST", credentials: "include", body: fd });
        if (r.ok) { cargar(); return; }
        const d = await r.json().catch(() => ({}));
        err.textContent = d.message || "No se pudo subir la referencia.";
      } catch (e) {
        err.textContent = "No se pudo subir la referencia.";
      }
      err.hidden = false;
      btn.disabled = false;
    });
    return tarjeta(el("h2", "Sube tu referencia bancaria", "h2"),
      el("p", "Con ella la secretaria arma tu plan de pagos. Solo PDF, máximo 5 MB.", "hint"), inp, btn, err);
  }

  function seccionCancelar(s) {
    const sec = el("section", null, "cancelar");
    const b = el("button", "Cancelar solicitud", "btn btn-ghost");
    b.type = "button";
    b.addEventListener("click", function () { cancelar(s.id, b); });
    sec.append(el("p", "¿Ya no la necesitas? Puedes cancelarla mientras esté pendiente, pero ya no podrás pedir otra este semestre.", "hint"), b);
    return sec;
  }

  // Tarjetas de una solicitud; `ultima` = la más reciente, `d` = la respuesta de /estado.
  function solicitud(s, ultima, d, titulo) {
    const [insignia, cls, texto] = ESTADO[s.estado] || [s.estado, "t-neutral", "Mi prórroga"];
    const estado = tarjeta(encabezado("Mi prórroga", insignia, cls), titulo(texto));
    const nodos = [estado];
    let firmaSec = null;
    if (s.estado === "pendiente") {
      estado.append(el("p", "No tienes que hacer nada por ahora. Vuelve a esta página para ver la respuesta.", "lead"), datos(s));
      nodos.push(plantilla("mp-revision"));
      if (s.cuenta.total === null) nodos.push(seccionReferencia(s));
    } else if (s.estado === "aceptada") {
      estado.append(resumenAceptada(s), datos(s));
      if (s.comentario) estado.append(el("p", "Comentario de la secretaria", "label"), el("p", s.comentario, "quote ok"));
      if (s.cuenta.total === null) nodos.push(seccionReferencia(s));
      if (s.por_firmar) nodos.push(firmaSec = seccionFirma(s));
      if (s.cuenta.total !== null) nodos.push(planDePagos(s.cuenta), recibos(s.recibos || []));
    } else {
      estado.append(datos(s));
      if (s.estado === "rechazada" && s.comentario) {
        nodos.push(tarjeta(el("h2", "¿Por qué?", "h2"), el("p", "Comentario de la secretaria", "label"), el("p", s.comentario, "quote")));
      }
    }
    if (s.documentos && s.documentos.length) nodos.push(documentos(s));
    if (s.estado === "pendiente") nodos.push(seccionCancelar(s));
    return { nodos, crearLienzo: function () { if (firmaSec) firmaSec.crear(); } };
  }

  async function cargar() {
    let d;
    try {
      const r = await fetch(`${API}/estado`, { credentials: "include" });
      d = await r.json();
      if (!r.ok) { mensaje(d.message || "No se pudo cargar tu información.", "error"); return; }
    } catch (e) {
      mensaje("No se pudo cargar tu información.", "error");
      return;
    }
    let conH1 = false;   // un solo h1 por página; los demás títulos de estado son h2 con el mismo estilo
    const titulo = (t) => { const e = el(conH1 ? "h2" : "h1", t, "h1"); conH1 = true; return e; };
    const sols = d.solicitudes || [], nodos = [];
    if (d.puede_solicitar) {
      const a = el("a", "Solicitar prórroga", "btn");
      a.href = "/prorrogas/estudiante/solicitud";
      a.append(icono("arrow"));
      nodos.push(tarjeta(encabezado("Estado", sols.length ? "Puedes solicitar" : "Sin solicitud", "t-neutral"), titulo("Mi prórroga"),
        el("p", sols.length ? "Puedes pedir una nueva prórroga aquí mismo." : "Todavía no has pedido una prórroga. Puedes hacerlo aquí mismo.", "lead"), a));
      if (!sols.length) nodos.push(plantilla("mp-como"));
    } else if (d.motivo === "no_hay_semestre" && !(sols[0] && ["pendiente", "aceptada"].includes(sols[0].estado))) {   // cerró el periodo pero su prórroga sigue viva
      nodos.push(tarjeta(el("p", "Mi prórroga", "label"), el("p", "Por ahora no hay un semestre abierto para prórrogas.", "lead")));
    } else if (d.motivo === "sin_acceso") {
      nodos.push(tarjeta(el("p", "Mi prórroga", "label"), el("p", "Pide tu acceso en la Subdirección Académica", "lead")));
    }
    const partes = sols.map((s, i) => solicitud(s, i === 0, d, titulo));
    partes.forEach(function (p) { nodos.push(...p.nodos); });
    if (!nodos.length) nodos.push(tarjeta(el("p", "Aún no tienes solicitudes.", "lead")));
    root.replaceChildren(...nodos);
    partes.forEach(function (p) { p.crearLienzo(); });
  }

  cargar();
})();
