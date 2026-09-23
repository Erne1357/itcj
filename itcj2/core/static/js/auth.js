// static/js/auth.js
(async () => {
  try {
    const r = await fetch("/api/core/v2/auth/me", { credentials: "include" });
    if (r.ok) {
      const { user } = await r.json();
      if (user?.role === "student") window.location.href = "/student/home";
      else if (user?.role === "coordinator") window.location.href = "/coord/home";
      else if (user?.role === "social_service") window.location.href = "/social/home";
      else window.location.href = "/";
    }
  } catch {}
})();

(() => {
  const form = document.getElementById("loginForm");
  const btn = document.getElementById("btnLogin");
  const alertBox = document.getElementById("alertBox");

  function showError(msg){ alertBox.textContent = msg || "Error al iniciar sesión."; alertBox.classList.remove("d-none"); }
  function hideError(){ alertBox.classList.add("d-none"); alertBox.textContent = ""; }

  form.addEventListener("submit", async (e) => {
    e.preventDefault(); hideError();
    if (!form.checkValidity()) { form.classList.add("was-validated"); return; }

    btn.disabled = true; btn.textContent = "Entrando...";

    const idOrUser = document.getElementById("control_number").value.trim(); // puede ser 8 dígitos o username
    const nip = document.getElementById("nip").value.trim();

    // Enviamos SIEMPRE el mismo payload; el backend decide si es alumno o staff
    const payload = { control_number: idOrUser, nip };

    try {
      const res = await fetch("/api/core/v2/auth/login", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      if (!res.ok) {
        if (res.status === 400) showError("Formato inválido. Revisa tus datos.");
        else if (res.status === 401) showError("Credenciales incorrectas.");
        else showError("Ocurrió un error. Intenta de nuevo.");
        return;
      }
      const { user } = await res.json();
      // `data-next` lo escribe el servidor YA validado (core/pages/auth.py:
      // safe_next). Se revalida aquí por si alguien inyecta el atributo desde
      // la consola: dos líneas, y el destino nunca sale del origen.
      const next = (form.dataset.next || "").trim();
      const nextOk = next.startsWith("/") && !next.startsWith("//") && !next.startsWith("/\\");
      if (nextOk) window.location.href = next;
      else if (user?.role === "student") window.location.href = "/itcj/m/";
      else if (user?.role === "coordinator") window.location.href = "/itcj/dashboard";
      else if (user?.role === "social_service") window.location.href = "/itcj/dashboard";
      else window.location.href = "/itcj/dashboard";
    } catch {
      showError("No se pudo conectar con el servidor.");
    } finally {
      btn.disabled = false; btn.textContent = "Iniciar sesión";
    }
  });
})();
