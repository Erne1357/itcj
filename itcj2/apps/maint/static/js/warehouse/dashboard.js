/**
 * warehouse/dashboard.js — Dashboard del almacén de mantenimiento
 */
'use strict';

(function () {

    var API = '/api/warehouse/v2';

    function load() {
        MaintUtils.api.fetch(API + '/dashboard')
            .then(function (d) {
                _animKpi('kpiProducts',  Number(d.total_products)  || 0);
                _animKpi('kpiLowStock',  Number(d.low_stock_count) || 0);
                _animKpi('kpiMovements', Number(d.movements_today) || 0);
                var val = parseFloat(d.total_stock_value || 0);
                var valEl = document.getElementById('kpiValue');
                if (window.MaintUtils && MaintUtils.animate) {
                    MaintUtils.animate.countUp(valEl, val, { duration: 800, decimals: 2, prefix: '$' });
                } else {
                    valEl.textContent = '$' + val.toFixed(2);
                }
                _renderLowStock(d.low_stock_products || []);
            })
            .catch(function () {
                document.getElementById('lowStockTable').innerHTML =
                    '<div class="alert alert-danger m-3">Error al cargar el dashboard.</div>';
            });
    }

    function _animKpi(id, n) {
        var el = document.getElementById(id);
        if (!el) return;
        if (window.MaintUtils && MaintUtils.animate) {
            MaintUtils.animate.countUp(el, n, { duration: 700 });
        } else {
            el.textContent = n;
        }
    }

    function _renderLowStock(products) {
        var container = document.getElementById('lowStockTable');
        if (!products.length) {
            container.innerHTML =
                '<div class="text-center text-success py-4">' +
                '<i class="bi bi-check-circle fs-2 d-block mb-2"></i>' +
                '<p class="mb-0">Todos los productos tienen stock suficiente.</p>' +
                '</div>';
            return;
        }
        var rows = products.map(function (p) {
            return '<tr class="mn-fade-in-up">' +
                '<td><span class="badge bg-secondary">' + _esc(p.code || '—') + '</span></td>' +
                '<td>' + _esc(p.name) + '</td>' +
                '<td><span class="text-danger fw-bold">' + p.total_stock + '</span> ' + _esc(p.unit_of_measure || '') + '</td>' +
                '<td>' + p.restock_point + '</td>' +
                '</tr>';
        }).join('');
        container.innerHTML =
            '<div class="table-responsive">' +
            '<table class="table table-hover mb-0">' +
            '<thead class="table-light"><tr><th>Código</th><th>Producto</th><th>Stock Actual</th><th>Punto Restock</th></tr></thead>' +
            '<tbody class="mn-stagger">' + rows + '</tbody>' +
            '</table></div>';
    }

    function _esc(s) {
        var d = document.createElement('div');
        d.appendChild(document.createTextNode(String(s || '')));
        return d.innerHTML;
    }

    document.addEventListener('DOMContentLoaded', load);

})();
