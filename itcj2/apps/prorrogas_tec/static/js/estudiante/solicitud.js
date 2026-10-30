(function () {
  const API = "/api/prorrogas/v2";
  const $ = (id) => document.getElementById(id);
  const form = $("sol-form"), canvas = $("sol-firma"), enviar = $("sol-enviar");
  const motivo = $("sol-motivo"), cuenta = $("sol-cuenta"), acepto = $("sol-acepto"), errorEl = $("sol-error");
  const carrera = $("sol-carrera");
  let firma = null;

  function bloquear(texto) {
    $("sol-bloqueo-msg").textContent = texto;
    $("sol-bloqueo").hidden = false;
  }

  function mostrarError(texto) {
    errorEl.textContent = texto;
    errorEl.hidden = !texto;
  }

  function actualizar() {
    const n = motivo.value.trim().length;
    cuenta.textContent = `${motivo.value.length} / 1000`;
    cuenta.classList.toggle("bad", n < 20);
    enviar.disabled = !(firma && !firma.vacia() && acepto.checked && carrera.value);
  }

  $("sol-borrar").addEventListener("click", function () { firma.limpiar(); });
  motivo.addEventListener("input", actualizar);
  acepto.addEventListener("change", actualizar);
  carrera.addEventListener("change", actualizar);

  form.addEventListener("submit", async function (e) {
    e.preventDefault();
    if (enviar.disabled) return;
    mostrarError("");
    if (motivo.value.trim().length < 20) { mostrarError("El motivo debe tener al menos 20 caracteres."); return; }
    enviar.disabled = true;
    try {
      const r = await fetch(`${API}/estudiante/solicitudes`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          plazos: parseInt($("sol-plazos").value, 10),
          motivo: motivo.value,
          program_id: parseInt(carrera.value, 10),
          firma: firma.dataURL(),
        }),
      });
      if (r.ok) { window.location.href = "/prorrogas/estudiante"; return; }
      const d = await r.json().catch(() => ({}));
      mostrarError(d.message || "No se pudo enviar la solicitud.");
    } catch (err) {
      mostrarError("No se pudo enviar la solicitud.");
    }
    actualizar();
  });

  async function iniciar() {
    let est, progs;
    try {
      const [a, b] = await Promise.all([
        fetch(`${API}/estudiante/estado`, { credentials: "include" }),
        fetch(`${API}/programs?limit=500`, { credentials: "include" }),
      ]);
      est = await a.json();
      progs = await b.json();
    } catch (e) {
      bloquear("No se pudo cargar tu información.");
      return;
    }
    if (!est.puede_solicitar) {
      bloquear(est.motivo === "sin_acceso" ? "Pide tu acceso en la Subdirección Académica"
        : est.motivo === "no_hay_semestre" ? "Por ahora no hay un semestre abierto para prórrogas."
        : "Ya tienes una solicitud abierta.");
      return;
    }
    (progs.items || []).forEach(function (p) {
      const o = document.createElement("option");
      o.value = p.id;
      o.textContent = p.name;
      carrera.append(o);
    });
    // Solo se preselecciona la carrera del perfil; si no hay, queda "Elige tu carrera".
    if (est.program_id != null) carrera.value = String(est.program_id);
    if (carrera.selectedIndex < 0) carrera.selectedIndex = 0;   // la del perfil no está en la lista
    form.hidden = false;
    firma = Firma.crear(canvas, actualizar);   // ya visible: mide el ancho real
    actualizar();
  }
  iniciar();
})();
