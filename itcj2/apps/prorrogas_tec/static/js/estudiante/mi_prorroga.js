(function () {
  const API = "/api/prorrogas/v2/estudiante";
  const root = document.getElementById("mp-root");

  function el(tag, text, cls) {
    const e = document.createElement(tag);
    if (text != null) e.textContent = text;
    if (cls) e.className = cls;
    return e;
  }

  function mensaje(texto, cls) {
    root.replaceChildren(el("p", texto, cls || "est-hint"));
  }

  async function cancelar(id, btn) {
    if (!confirm("¿Cancelar esta solicitud?")) return;
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

  const ESTADO_PARCIALIDAD = { pagada: "Pagada", parcial: "Parcial", pendiente: "Pendiente", vencida: "Vencida" };

  function fecha(iso) {
    const [y, m, d] = String(iso).split("-");
    return d && m && y ? `${d}/${m}/${y}` : String(iso);
  }
  const dinero = (v) => "$" + v;

  function seccionCuenta(c, recibos) {
    const sec = el("div", null, "mp-cuenta");
    if (c.total === null) {
      sec.append(el("p", "La secretaria todavía no arma tu plan de pagos.", "est-hint"));
      return sec;
    }
    sec.append(el("h2", "Tu plan de pagos", "est-h2"));
    if (c.situacion === "liquidada") sec.append(el("p", "Prórroga liquidada", "est-ok"));
    const ul = el("ul", null, "mp-plan");
    (c.parcialidades || []).forEach(function (p) {
      let t = `${p.numero}. ${dinero(p.monto)} · ${fecha(p.fecha)} · ${ESTADO_PARCIALIDAD[p.estado] || p.estado}`;
      if (p.estado === "parcial") t += ` (${dinero(p.cubierto)} cubierto de ${dinero(p.monto)})`;
      ul.append(el("li", t, "mp-parc " + p.estado));
    });
    sec.append(ul);
    sec.append(el("p", `Total ${dinero(c.total)} · Pagado ${dinero(c.pagado)} · Saldo ${dinero(c.saldo)}`, "mp-saldo"));
    sec.append(el("h2", "Recibos registrados", "est-h2"));
    if (recibos && recibos.length) {
      const rl = el("ul", null, "mp-recibos");
      recibos.forEach(function (r) { rl.append(el("li", `${r.folio} · ${fecha(r.fecha)} · ${dinero(r.monto)}`)); });
      sec.append(rl);
    } else {
      sec.append(el("p", "Aún no hay recibos registrados.", "est-hint"));
    }
    return sec;
  }

  function seccionFirma(s) {
    const sec = document.getElementById("mp-firma-tpl").content.firstElementChild.cloneNode(true);
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

  function tarjeta(s) {
    const box = el("div", null, "est-sol");
    const h = el("div");
    h.append(el("span", s.folio, "est-folio"), el("span", s.estado, "est-estado " + s.estado));
    box.append(h);
    box.append(el("p", `${s.semestre || ""} · ${s.plazos} plazo(s)`, "est-hint"));
    if (s.comentario) box.append(el("p", "Comentario de la secretaria: " + s.comentario, "est-hint"));
    if (s.documentos && s.documentos.length) {
      const ul = el("ul", null, "est-docs");
      s.documentos.forEach(function (d) {
        const li = el("li");
        const a = el("a", d.label + (d.firmado ? " (firmado)" : ""));
        a.href = `${API}/solicitudes/${s.id}/documentos/${d.id}.pdf`;
        a.target = "_blank";
        a.rel = "noopener";
        li.append(a);
        ul.append(li);
      });
      box.append(ul);
    }
    let firmaSec = null;
    if (s.estado === "aceptada") {
      box.append(seccionCuenta(s.cuenta, s.recibos));
      if (s.por_firmar) box.append(firmaSec = seccionFirma(s));
    }
    box.crearLienzo = function () { if (firmaSec) firmaSec.crear(); };
    if (s.estado === "pendiente") {
      const b = el("button", "Cancelar", "est-btn est-btn-sec");
      b.type = "button";
      b.addEventListener("click", function () { cancelar(s.id, b); });
      box.append(b);
    }
    return box;
  }

  async function cargar() {
    let d;
    try {
      const r = await fetch(`${API}/estado`, { credentials: "include" });
      d = await r.json();
      if (!r.ok) { mensaje(d.message || "No se pudo cargar tu información.", "est-error"); return; }
    } catch (e) {
      mensaje("No se pudo cargar tu información.", "est-error");
      return;
    }
    const nodos = [];
    if (d.puede_solicitar) {
      const a = el("a", "Solicitar prórroga", "est-btn");
      a.href = "/prorrogas/estudiante/solicitud";
      nodos.push(a);
    } else if (d.motivo === "sin_acceso") {
      nodos.push(el("p", "Pide tu acceso en la Subdirección Académica", "est-hint"));
    } else if (d.motivo === "no_hay_semestre") {
      nodos.push(el("p", "Por ahora no hay un semestre abierto para prórrogas.", "est-hint"));
    }
    const tarjetas = (d.solicitudes || []).map(tarjeta);
    nodos.push.apply(nodos, tarjetas);
    if (!nodos.length) nodos.push(el("p", "Aún no tienes solicitudes.", "est-hint"));
    root.replaceChildren.apply(root, nodos);
    tarjetas.forEach(function (t) { t.crearLienzo(); });
  }

  cargar();
})();
