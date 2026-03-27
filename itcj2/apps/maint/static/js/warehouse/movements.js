/**
 * warehouse/movements.js — Historial de movimientos del almacén de mantenimiento
 */
'use strict';

(function () {

    var API = '/api/maint/v2/warehouse';
    var _currentPage = 1;
    var _totalPages = 1;

    var TYPE_LABELS = {
        ENTRY:        { label: 'Entrada',      cls: 'bg-success' },
        CONSUMED:     { label: 'Consumo',      cls: 'bg-primary' },
        ADJUSTED_IN:  { label: 'Ajuste +',     cls: 'bg-info' },
        ADJUSTED_OUT: { label: 'Ajuste -',     cls: 'bg-warning text-dark' },
        RETURNED:     { label: 'Devolución',   cls: 'bg-secondary' },
        VOIDED:       { label: 'Anulado',      cls: 'bg-dark' },
    };

    window.MaintWarehouseMovements = {
        load: function () { _load(1); },
        prevPage: function () { if (_currentPage > 1) _load(_currentPage - 1); },
        nextPage: function () { if (_currentPage < _totalPages) _load(_currentPage + 1); },
    };

    function _loadProducts() {
        MaintUtils.api.fetch(API + '/products')
            .then(function (d) {
                var opts = (d.products || []).map(function (p) {
                    return '<option value="' + p.id + '">' + _esc(p.code || p.id) + ' — ' + _esc(p.name) + '</option>';
                }).join('');
                document.getElementById('productFilter').insertAdjacentHTML('beforeend', opts);
            })
            .catch(function (err) { console.error(err); });
    }

    function _load(page) {
        _currentPage = page || 1;
        var params = new URLSearchParams({ page: _currentPage, per_page: 30 });
        var productId = document.getElementById('productFilter').value;
        var type = document.getElementById('typeFilter').value;
        if (productId) params.set('product_id', productId);
        if (type) params.set('movement_type', type);

        document.getElementById('movementsContainer').innerHTML =
            '<div class="text-center py-5"><div class="spinner-border" style="color:var(--maint-primary);" role="status"></div></div>';

        MaintUtils.api.fetch(API + '/movements?' + params.toString())
            .then(function (d) {
                _totalPages = d.pages || 1;
                _renderMovements(d.movements || []);
                _renderPagination(d.total || 0, _currentPage, _totalPages);
            })
            .catch(function () {
                document.getElementById('movementsContainer').innerHTML =
                    '<div class="alert alert-danger m-3">Error al cargar movimientos.</div>';
            });
    }

    function _renderMovements(movements) {
        if (!movements.length) {
            document.getElementById('movementsContainer').innerHTML =
                '<div class="text-center py-5 text-muted"><i class="bi bi-arrow-left-right fs-1 d-block mb-3"></i><p>Sin movimientos.</p></div>';
            return;
        }
        var rows = movements.map(function (m) {
            var type = TYPE_LABELS[m.movement_type] || { label: m.movement_type, cls: 'bg-secondary' };
            var date = m.performed_at ? new Date(m.performed_at).toLocaleString('es-MX', {
                day: '2-digit', month: '2-digit', year: '2-digit',
                hour: '2-digit', minute: '2-digit'
            }) : '—';
            var ticket = m.source_ticket_id
                ? '<small class="text-muted">' + _esc(m.source_app || '') + ' #' + m.source_ticket_id + '</small>'
                : '—';
            return '<tr>' +
                '<td><small>' + date + '</small></td>' +
                '<td class="small">' + _esc(m.product_name || ('Producto #' + m.product_id)) + '</td>' +
                '<td><span class="badge ' + type.cls + '">' + type.label + '</span></td>' +
                '<td class="text-end">' + m.quantity + '</td>' +
                '<td>' + ticket + '</td>' +
                '<td class="text-muted small">' + _esc(m.notes || '—') + '</td>' +
                '</tr>';
        }).join('');
        document.getElementById('movementsContainer').innerHTML =
            '<div class="table-responsive">' +
            '<table class="table table-hover table-sm mb-0">' +
            '<thead class="table-light"><tr><th>Fecha</th><th>Producto</th><th>Tipo</th><th class="text-end">Cantidad</th><th>Origen</th><th>Notas</th></tr></thead>' +
            '<tbody>' + rows + '</tbody></table></div>';
    }

    function _renderPagination(total, page, pages) {
        var pag = document.getElementById('pagination');
        pag.classList.remove('d-none');
        document.getElementById('paginationInfo').textContent = 'Página ' + page + ' de ' + pages + ' (' + total + ' movimientos)';
        document.getElementById('btnPrev').disabled = page <= 1;
        document.getElementById('btnNext').disabled = page >= pages;
    }

    function _esc(s) {
        var d = document.createElement('div');
        d.appendChild(document.createTextNode(String(s || '')));
        return d.innerHTML;
    }

    document.addEventListener('DOMContentLoaded', function () {
        _loadProducts();
        _load(1);
    });

})();
