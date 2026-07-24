// AgendaTec — logout (delegado a #btnLogout; el sidebar móvil lo dispara vía shared/base.js).
// Iframe-aware: dentro del dashboard móvil NO se redirige el iframe; se notifica
// al parent para que redirija la ventana top. Standalone sí redirige.
document.addEventListener("click", async (e) => {
  if (!e.target || !e.target.closest("#btnLogout")) return;

  const inIframe = window.self !== window.top;
  try {
    await fetch("/api/core/v2/auth/logout", { method: "POST", credentials: "include" });
  } catch {}

  if (inIframe) {
    try {
      window.parent.postMessage(
        { type: "LOGOUT", source: "agendatec", reason: "manual_logout" },
        window.location.origin
      );
    } catch {}
  } else {
    window.location.href = "/itcj/login";
  }
});
