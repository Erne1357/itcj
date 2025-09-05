// static/js/auth.js
(async () => {
  try {
    const r = await fetch("/api/auth/v1/auth/me", { credentials: "include" });
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
      const res = await fetch("/api/auth/v1/auth/login", {
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
      if (user?.role === "student") window.location.href = "/agendatec/student/home";
      else if (user?.role === "coordinator") window.location.href = "/dashboard/dashboard";
      else if (user?.role === "social_service") window.location.href = "/dashboard/dashboard";
      else window.location.href = "/";
    } catch {
      showError("No se pudo conectar con el servidor.");
    } finally {
      btn.disabled = false; btn.textContent = "Iniciar sesión";
    }
  });
})();
