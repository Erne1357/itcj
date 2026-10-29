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
    (d.solicitudes || []).forEach(function (s) { nodos.push(tarjeta(s)); });
    if (!nodos.length) nodos.push(el("p", "Aún no tienes solicitudes.", "est-hint"));
    root.replaceChildren.apply(root, nodos);
  }

  cargar();
})();
