/**
 * AgendaTec Admin — Encuestas
 * Gestión de sesión Microsoft y envío de encuestas por correo.
 * Bootstrap Tab API maneja la navegación de pestañas.
 */
(function () {
  "use strict";

  const $ = s => document.querySelector(s);

  // === ESTADO ===
  async function refreshStatus() {
    try {
      const r = await fetch("/itcj/config/email/auth/status?app=agendatec", { credentials: "include" });
      const j = await r.json();
      const badge = $("#msStatus");
      const txt = $("#msAccountTxt");
      if (!badge || !txt) return;
      if (j.connected) {
        badge.textContent = "Conectado";
        badge.className = "badge text-bg-success";
        const who = j?.account?.username || "—";
        txt.innerHTML = `Conectado como <strong>${escapeHtml(who)}</strong>`;
      } else {
        badge.textContent = "Sin sesión";
        badge.className = "badge text-bg-secondary";
        txt.textContent = "No hay sesión activa";
      }
    } catch (_) {
      const badge = $("#msStatus");
      if (badge) {
        badge.textContent = "Error";
        badge.className = "badge text-bg-danger";
      }
    }
  }

  // === ENVÍO ===
  async function handleSend() {
    const btn = $("#btnSend");
    const out = $("#out");
    if (!btn || !out) return;

    const originalHtml = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1" role="status" aria-hidden="true"></span>Enviando...';
    out.textContent = "Enviando...\n";

    try {
      const f = $("#fromDate")?.value || "";
      const t = $("#toDate")?.value || "";
      const test = $("#testMode")?.checked ? 1 : 0;

      const u = new URL(window.__surveysCfg.sendUrl, window.location.origin);
      if (f) u.searchParams.set("from", f);
      if (t) u.searchParams.set("to", t);
      u.searchParams.set("test", String(test));
      u.searchParams.set("limit", "700");
      u.searchParams.set("offset", "0");

      const r = await fetch(u, { method: "POST", credentials: "include" });
      const j = await r.json().catch(() => ({}));
      out.textContent += JSON.stringify(j, null, 2);
    } catch (err) {
      out.textContent += `\nError: ${err.message}`;
    } finally {
      btn.disabled = false;
      btn.innerHTML = originalHtml;
    }
  }

  // === UTILIDADES ===
  function escapeHtml(str) {
    if (!str) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  // === INICIALIZACIÓN ===
  document.addEventListener("DOMContentLoaded", function () {
    // Fechas por defecto: últimos 7 días
    const to = new Date();
    const from = new Date(Date.now() - 7 * 86400000);
    const toEl = $("#toDate");
    const fromEl = $("#fromDate");
    if (toEl) toEl.value = to.toISOString().slice(0, 10);
    if (fromEl) fromEl.value = from.toISOString().slice(0, 10);

    // Logout Microsoft
    $("#btnMsLogout")?.addEventListener("click", async () => {
      await fetch("/itcj/config/email/auth/logout?app=agendatec", {
        method: "POST",
        credentials: "include"
      });
      refreshStatus();
    });

    // Enviar encuestas
    $("#btnSend")?.addEventListener("click", handleSend);

    // Verificar estado de conexión al cargar
    refreshStatus();
  });
})();
