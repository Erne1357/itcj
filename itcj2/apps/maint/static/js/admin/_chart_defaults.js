/**
 * _chart_defaults.js
 * Configura los defaults globales de Chart.js con la paleta de marca de Maint.
 * Cargar antes del script principal de cada página.
 */
'use strict';

(function () {

    if (typeof Chart === 'undefined') return;

    var MAINT_PRIMARY      = '#546E7A';
    var MAINT_PRIMARY_DARK = '#37474F';
    var MAINT_MUTED        = '#607D8B';
    var MAINT_BORDER       = '#CFD8DC';
    var FONT_STACK         = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif";

    Chart.defaults.color          = MAINT_MUTED;
    Chart.defaults.borderColor    = MAINT_BORDER;
    Chart.defaults.font.family    = FONT_STACK;
    Chart.defaults.font.size      = 12;
    Chart.defaults.plugins.legend.labels.color = MAINT_PRIMARY_DARK;
    Chart.defaults.plugins.tooltip.backgroundColor = MAINT_PRIMARY_DARK;
    Chart.defaults.plugins.tooltip.titleColor      = '#ECEFF1';
    Chart.defaults.plugins.tooltip.bodyColor       = '#B0BEC5';
    Chart.defaults.plugins.tooltip.borderColor     = MAINT_PRIMARY;
    Chart.defaults.plugins.tooltip.borderWidth     = 1;

})();
