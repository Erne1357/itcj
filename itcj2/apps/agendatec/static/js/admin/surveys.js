(function () {
  const $ = s => document.querySelector(s);

  // tabs
  document.querySelectorAll(".tab-btn").forEach(a => {
    a.addEventListener("click", function () {
      document.querySelectorAll(".nav-link").forEach(x => x.classList.remove("active"));
      document.querySelectorAll(".tab-pane").forEach(x => x.classList.remove("show", "active"));
      a.classList.add("active");
      const tgt = a.getAttribute("data-target");
      const pane = document.querySelector(tgt);
      pane.classList.add("show", "active");
    });
  });

  async function refreshStatus() {
    const r = await fetch("/itcj/config/email/auth/status?app=agendatec", { credentials: "include" });
    const j = await r.json();
    $("#msStatus").textContent = j.connected ? "Conectado" : "Sin sesion";
    $("#msStatus").className = j.connected ? "badge text-bg-success" : "badge text-bg-secondary";
    const who = j?.account?.username || "\u2014";
    $("#msAccountTxt").innerHTML = j.connected
      ? `Conectado como <strong>${who}</strong>`
      : "No hay sesion activa";
  }

  $("#btnMsLogout")?.addEventListener("click", async () => {
    await fetch("/itcj/config/email/auth/logout?app=agendatec", { method: "POST", credentials: "include" });
    refreshStatus();
  });

  // enviar
  $("#btnSend")?.addEventListener("click", async () => {
    const f = $("#fromDate").value, t = $("#toDate").value, test = $("#testMode").checked ? 1 : 0;
    const out = $("#out");
    out.textContent = "Enviando...\n";
    const u = new URL(window.__surveysCfg.sendUrl, window.location.origin);
    if (f) u.searchParams.set("from", f);
    if (t) u.searchParams.set("to", t);
    u.searchParams.set("test", String(test));
    u.searchParams.set("limit", "700"); u.searchParams.set("offset", "0");
    const r = await fetch(u, { method: "POST", credentials: "include" });
    const j = await r.json().catch(() => ({}));
    out.textContent += JSON.stringify(j, null, 2);
  });

  // fechas por defecto
  const to = new Date(); const from = new Date(Date.now() - 7 * 86400000);
  $("#toDate").value = to.toISOString().slice(0, 10);
  $("#fromDate").value = from.toISOString().slice(0, 10);

  refreshStatus();
})();
