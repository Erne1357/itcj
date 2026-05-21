/* =============================================================================
   AgendaTec — Shared formatters
   -----------------------------------------------------------------------------
   Funciones puras reutilizables entre coord/admin/social/student.
   Expone window.AgendaTec.Format.
   ============================================================================= */
(function () {
  "use strict";

  const MONTHS_ES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun",
                     "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"];

  const WEEKDAYS_ES = ["Dom", "Lun", "Mar", "Mié", "Jue", "Vie", "Sáb"];

  const WEEKDAYS_LONG_ES = ["Domingo", "Lunes", "Martes", "Miércoles",
                            "Jueves", "Viernes", "Sábado"];

  /**
   * Parsea ISO date (YYYY-MM-DD) sin desfase de timezone.
   * @param {string} iso "2026-05-19"
   * @returns {Date}
   */
  function parseISODate(iso) {
    if (!iso) return null;
    const [y, m, d] = iso.split("-").map(Number);
    return new Date(y, m - 1, d);
  }

  /**
   * "Lun 25 Ago" — formato completo para selectores coord/slots.
   */
  function formatDayLabel(iso) {
    const d = parseISODate(iso);
    if (!d) return iso || "";
    return `${WEEKDAYS_ES[d.getDay()]} ${d.getDate()} ${MONTHS_ES[d.getMonth()]}`;
  }

  /**
   * "25 Ago" — formato corto (mismo formato en TODAS las páginas a partir de Fase 2).
   * Se mantiene la función por compat. Recomendado: usar formatDayLabel.
   */
  function formatDayLabelShort(iso) {
    const d = parseISODate(iso);
    if (!d) return iso || "";
    return `${d.getDate()} ${MONTHS_ES[d.getMonth()]}`;
  }

  /**
   * "Lunes 25 de Agosto" — formato largo para títulos.
   */
  function formatDayLabelLong(iso) {
    const d = parseISODate(iso);
    if (!d) return iso || "";
    return `${WEEKDAYS_LONG_ES[d.getDay()]} ${d.getDate()} de ${MONTHS_ES[d.getMonth()]}`;
  }

  /**
   * "HH:MM" — recorta segundos si vienen.
   */
  function formatTime(value) {
    if (!value) return "";
    const s = String(value);
    return s.length >= 5 ? s.substring(0, 5) : s;
  }

  /**
   * "HH:MM - HH:MM" rango horario.
   */
  function formatTimeRange(start, end) {
    return `${formatTime(start)} - ${formatTime(end)}`;
  }

  /**
   * Escape HTML para prevenir XSS en innerHTML.
   */
  function escapeHtml(str) {
    if (str === null || str === undefined) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  /**
   * Debounce — usado para sockets que disparan rápido en ráfaga.
   */
  function debounce(fn, wait) {
    let t = null;
    return function (...args) {
      clearTimeout(t);
      t = setTimeout(() => fn.apply(this, args), wait);
    };
  }

  window.AgendaTec = window.AgendaTec || {};
  window.AgendaTec.Format = {
    parseISODate,
    formatDayLabel,
    formatDayLabelShort,
    formatDayLabelLong,
    formatTime,
    formatTimeRange,
    escapeHtml,
    debounce,
    MONTHS_ES,
    WEEKDAYS_ES,
  };
})();
