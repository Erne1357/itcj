document.addEventListener("click", async (e) => {
  if (e.target && e.target.id === "btnLogout") {
    try {
      await fetch("/api/auth/v1/auth/logout", { method: "POST", credentials: "include" });
    } catch {}
    window.location.href = "/auth/login";
  }
});
