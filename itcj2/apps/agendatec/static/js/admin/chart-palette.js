/* =============================================================================
   AgendaTec — Chart Palette centralizada
   -----------------------------------------------------------------------------
   Expone window.AgendaTec.ChartPalette con colores derivados de tokens CSS,
   etiquetas en español y opciones base para Chart.js.
   Cargado antes de home_pies.js, home_bars.js, home_activity.js.
   ============================================================================= */
(function () {
  "use strict";

  function cssVar(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }

  /* ---- Colores por estado de solicitud ------------------------------------ */
  const statusColors = {
    PENDING:                cssVar("--at-warning"),
    RESOLVED_SUCCESS:       cssVar("--at-success"),
    RESOLVED_NOT_COMPLETED: cssVar("--at-text-muted"),
    ATTENDED_OTHER_SLOT:    cssVar("--at-info"),
    NO_SHOW:                cssVar("--at-danger"),
    CANCELED:               cssVar("--at-text-disabled"),
  };

  /* ---- Etiquetas en español ----------------------------------------------- */
  const statusLabels = {
    PENDING:                "Pendientes",
    RESOLVED_SUCCESS:       "Resueltas",
    RESOLVED_NOT_COMPLETED: "Atendidas sin resolver",
    ATTENDED_OTHER_SLOT:    "Otro horario",
    NO_SHOW:                "No asistió",
    CANCELED:               "Canceladas",
  };

  /* Orden canónico de estados */
  const STATUS_ORDER = [
    "PENDING",
    "RESOLVED_SUCCESS",
    "RESOLVED_NOT_COMPLETED",
    "ATTENDED_OTHER_SLOT",
    "NO_SHOW",
    "CANCELED",
  ];

  /* Array de colores en el orden canónico (para datasets) */
  const statusColorArray = STATUS_ORDER.map((k) => statusColors[k]);

  /* ---- Paleta para coordinadores (12 rotaciones) -------------------------- */
  const coordColors = [
    cssVar("--at-primary"),
    cssVar("--at-info"),
    cssVar("--at-success"),
    cssVar("--at-warning"),
    cssVar("--at-danger"),
    cssVar("--at-primary-100"),
    "#6f42c1",   /* purple — sin token específico, cercano a BS */
    "#fd7e14",   /* orange */
    "#20c997",   /* teal */
    "#0dcaf0",   /* cyan */
    "#adb5bd",   /* gray-400 */
    "#343a40",   /* dark */
  ];

  /* ---- Opciones base Chart.js -------------------------------------------- */
  const borderSubtle = cssVar("--at-border-subtle");
  const textMuted    = cssVar("--at-text-muted");
  const textBase     = cssVar("--at-text");

  const chartDefaults = {
    font: {
      family: "'Segoe UI', system-ui, sans-serif",
      size: 12,
    },
    color: textMuted,
    animation: { duration: 200 },
    plugins: {
      legend: {
        labels: {
          color: textBase,
          font: { size: 12 },
          boxWidth: 12,
          padding: 12,
        },
      },
      tooltip: {
        backgroundColor: cssVar("--at-surface"),
        borderColor: cssVar("--at-border"),
        borderWidth: 1,
        titleColor: textBase,
        bodyColor: textMuted,
      },
    },
    scales: {
      x: {
        grid: { color: borderSubtle },
        ticks: { color: textMuted, font: { size: 11 } },
      },
      y: {
        grid: { color: borderSubtle },
        ticks: { color: textMuted, font: { size: 11 } },
      },
    },
  };

  window.AgendaTec = window.AgendaTec || {};
  window.AgendaTec.ChartPalette = {
    statusColors,
    statusLabels,
    STATUS_ORDER,
    statusColorArray,
    coordColors,
    chartDefaults,
  };
})();
