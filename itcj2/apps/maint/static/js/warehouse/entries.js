/**
 * warehouse/entries.js — Entradas de stock del almacén de mantenimiento
 */
'use strict';

(function () {

    var API = '/api/maint/v2/warehouse';
    var _currentPage = 1;
    var _totalPages = 1;

    window.MaintWarehouseEntries = {
        load: function () { _load(1); },
        prevPage: function () { if (_currentPage > 1) _load(_currentPage - 1); },
        nextPage: function () { if (_currentPage < _totalPages) _load(_currentPage + 1); },
        save: function () { _save(); },
        voidEntry: function (id) { _voidEntry(id); },
        confirmVoid: function () { _confirmVoid(); },
    };

    function _loadProducts() {
        MaintUtils.api.fetch(API + '/products')
            .then(function (d) {
                var opts = (d.products || []).map(function (p) {
                    return '<option value="' + p.id + '">' + _esc(p.code || p.id) + ' — ' + _esc(p.name) + '</option>';
                }).join('');
                document.getElementById('productFilter').insertAdjacentHTML('beforeend', opts);
                document.getElementById('entryProduct').innerHTML =
                    '<option value="">Selecciona un producto...</option>' + opts;
            })
            .catch(function (err) { console.error(err); });
    }

    function _load(page) {
        _currentPage = page || 1;
        var productId = document.getElementById('productFilter').value;
        var includeVoided = document.getElementById('includeVoided').checked;

        var params = new URLSearchParams({ page: _currentPage, per_page: 20 });
        if (productId) params.set('product_id', productId);
        if (includeVoided) params.set('include_voided', 'true');

        document.getElementById('entriesContainer').innerHTML =
            '<div class="text-center py-5"><div class="spinner-border" style="color:var(--maint-primary);" role="status"></div></div>';

        MaintUtils.api.fetch(API + '/stock-entries?' + params.toString())
            .then(function (d) {
                _totalPages = d.pages || 1;
                _renderEntries(d.entries || []);
                _renderPagination(d.total || 0, _currentPage, _totalPages);
            })
            .catch(function () {
                document.getElementById('entriesContainer').innerHTML =
                    '<div class="alert alert-danger m-3">Error al cargar entradas.</div>';
            });
    }

    function _renderEntries(entries) {
        if (!entries.length) {
            document.getElementById('entriesContainer').innerHTML =
                '<div class="text-center py-5 text-muted"><i class="bi bi-inbox fs-1 d-block mb-3"></i><p>Sin entradas.</p></div>';
            return;
        }
        var rows = entries.map(function (e) {
            var orig = parseFloat(e.quantity_original);
            var rem = parseFloat(e.quantity_remaining);
            var pct = orig > 0 ? Math.round((rem / orig) * 100) : 0;
            var badge = '<span class="badge bg-success">Disponible</span>';
            if (e.voided) badge = '<span class="badge bg-secondary">Anulada</span>';
            else if (e.is_exhausted) badge = '<span class="badge bg-dark">Agotada</span>';
            else if (pct < 30) badge = '<span class="badge bg-warning text-dark">Bajo</span>';

            return '<tr class="' + (e.voided ? 'table-secondary text-muted' : '') + '">' +
                '<td><code>' + _esc(e.purchase_folio || '—') + '</code></td>' +
                '<td><small>' + _esc(e.purchase_date) + '</small></td>' +
                '<td>' +
                '<div class="d-flex align-items-center gap-2">' +
                '<div class="progress flex-grow-1" style="height:8px;min-width:50px;"><div class="progress-bar" style="width:' + pct + '%;background:var(--maint-primary);"></div></div>' +
                '<small>' + rem + '/' + orig + '</small>' +
                '</div></td>' +
                '<td>$' + parseFloat(e.unit_cost || 0).toFixed(2) + '</td>' +
                '<td>' + _esc(e.supplier || '—') + '</td>' +
                '<td>' + badge + '</td>' +
                '<td>' +
                (!e.voided && !e.is_exhausted
                    ? '<button class="btn btn-sm btn-outline-danger" onclick="MaintWarehouseEntries.voidEntry(' + e.id + ')"><i class="bi bi-ban"></i></button>'
                    : '') +
                '</td>' +
                '</tr>';
        }).join('');
        document.getElementById('entriesContainer').innerHTML =
            '<div class="table-responsive">' +
            '<table class="table table-hover mb-0">' +
            '<thead class="table-light"><tr><th>Folio</th><th>Fecha</th><th>Restante/Original</th><th>Costo</th><th>Proveedor</th><th>Estado</th><th></th></tr></thead>' +
            '<tbody>' + rows + '</tbody></table></div>';
    }

    function _renderPagination(total, page, pages) {
        var pag = document.getElementById('pagination');
        pag.classList.remove('d-none');
        document.getElementById('paginationInfo').textContent = 'Página ' + page + ' de ' + pages + ' (' + total + ' entradas)';
        document.getElementById('btnPrev').disabled = page <= 1;
        document.getElementById('btnNext').disabled = page >= pages;
    }

    function _save() {
        var body = {
            product_id: parseInt(document.getElementById('entryProduct').value),
            quantity: parseFloat(document.getElementById('entryQty').value),
            unit_cost: parseFloat(document.getElementById('entryCost').value) || 0,
            purchase_folio: document.getElementById('entryFolio').value.trim() || null,
            supplier: document.getElementById('entrySupplier').value.trim() || null,
            purchase_date: document.getElementById('entryDate').value,
            notes: document.getElementById('entryNotes').value.trim() || null,
        };
        if (!body.product_id || !body.quantity || !body.purchase_date) {
            MaintUtils.toast('Completa los campos obligatorios.', 'warning');
            return;
        }
        MaintUtils.api.fetch(API + '/stock-entries', { method: 'POST', body: JSON.stringify(body) })
            .then(function () {
                bootstrap.Modal.getInstance(document.getElementById('entryModal')).hide();
                MaintUtils.toast('Entrada registrada exitosamente.', 'success');
                _load(1);
            })
            .catch(function (err) { MaintUtils.toast(err.message, 'error'); });
    }

    function _voidEntry(id) {
        document.getElementById('voidEntryId').value = id;
        document.getElementById('voidReason').value = '';
        new bootstrap.Modal(document.getElementById('voidModal')).show();
    }

    function _confirmVoid() {
        var id = document.getElementById('voidEntryId').value;
        var reason = document.getElementById('voidReason').value.trim();
        if (!reason) { MaintUtils.toast('La razón es obligatoria.', 'warning'); return; }
        MaintUtils.api.fetch(API + '/stock-entries/' + id + '/void', {
            method: 'POST', body: JSON.stringify({ reason: reason }),
        })
            .then(function () {
                bootstrap.Modal.getInstance(document.getElementById('voidModal')).hide();
                MaintUtils.toast('Entrada anulada.', 'success');
                _load(_currentPage);
            })
            .catch(function (err) { MaintUtils.toast(err.message, 'error'); });
    }

    function _esc(s) {
        var d = document.createElement('div');
        d.appendChild(document.createTextNode(String(s || '')));
        return d.innerHTML;
    }

    document.addEventListener('DOMContentLoaded', function () {
        document.getElementById('entryDate').value = new Date().toISOString().split('T')[0];
        _loadProducts();
        _load(1);
    });

})();
