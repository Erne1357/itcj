(function () {
  const API = "/api/prorrogas/v2";
  const $ = (id) => document.getElementById(id);
  const form = $("sol-form"), canvas = $("sol-firma"), enviar = $("sol-enviar");
  const motivo = $("sol-motivo"), cuenta = $("sol-cuenta"), acepto = $("sol-acepto"), errorEl = $("sol-error");
  const carrera = $("sol-carrera");
  const ctx = canvas.getContext("2d");
  let trazos = 0, dibujando = false;

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
    enviar.disabled = !(trazos > 0 && acepto.checked && carrera.value);
  }

  // El fondo queda transparente: el servidor rechaza una firma sin trazos o sin alfa.
  function ajustarLienzo() {
    const r = window.devicePixelRatio || 1, w = canvas.clientWidth, h = canvas.clientHeight;
    canvas.width = Math.round(w * r);
    canvas.height = Math.round(h * r);
    ctx.setTransform(r, 0, 0, r, 0, 0);
    ctx.lineWidth = 2.2;
    ctx.lineCap = ctx.lineJoin = "round";
    ctx.strokeStyle = "#1A130E";
    trazos = 0;
    actualizar();
  }

  function punto(e) {
    const b = canvas.getBoundingClientRect();
    return [e.clientX - b.left, e.clientY - b.top];
  }

  canvas.addEventListener("pointerdown", function (e) {
    dibujando = true;
    canvas.setPointerCapture(e.pointerId);
    const [x, y] = punto(e);
    ctx.beginPath();
    ctx.moveTo(x, y);
    ctx.lineTo(x + .01, y);
    ctx.stroke();
    e.preventDefault();
  });
  canvas.addEventListener("pointermove", function (e) {
    if (!dibujando) return;
    const [x, y] = punto(e);
    ctx.lineTo(x, y);
    ctx.stroke();
  });
  function fin() {
    if (!dibujando) return;
    dibujando = false;
    trazos++;
    actualizar();
  }
  canvas.addEventListener("pointerup", fin);
  canvas.addEventListener("pointercancel", fin);

  $("sol-borrar").addEventListener("click", function () {
    ctx.save();
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.restore();
    trazos = 0;
    actualizar();
  });
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
          firma: canvas.toDataURL("image/png"),
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
    ajustarLienzo();
  }
  iniciar();
})();
