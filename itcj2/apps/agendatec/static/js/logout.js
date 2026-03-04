document.addEventListener("click", async (e) => {
  if (e.target && e.target.id === "btnLogout") {
    try {
      await fetch("/api/core/v2/auth/logout", { method: "POST", credentials: "include" });
    } catch {}
    window.location.href = "/itcj/login";
  }
});
