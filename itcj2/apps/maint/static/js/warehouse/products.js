/**
 * warehouse/products.js — Catálogo de productos del almacén de mantenimiento
 */
'use strict';

(function () {

    var API = '/api/warehouse/v2';
    var _currentPage = 1;
    var _totalPages = 1;
    var _editingId = null;

    window.MaintWarehouseProducts = {
        load: function () { _load(1); },
        reset: function () { _reset(); },
        prevPage: function () { if (_currentPage > 1) _load(_currentPage - 1); },
        nextPage: function () { if (_currentPage < _totalPages) _load(_currentPage + 1); },
        showStock: function (productId, name) { _showStock(productId, name); },
        edit: function (productId) { _edit(productId); },
        save: function () { _save(); },
        openAdjust: function (productId, name) { _openAdjust(productId, name); },
        saveAdjust: function () { _saveAdjust(); },
    };

    function _loadCategories() {
        MaintUtils.api.fetch(API + '/categories?with_subcategories=true')
            .then(function (d) {
                var catFilter = document.getElementById('categoryFilter');
                var subcatSelect = document.getElementById('prodSubcategory');
                (d.categories || []).forEach(function (c) {
                    catFilter.insertAdjacentHTML('beforeend', '<option value="' + c.id + '">' + _esc(c.name) + '</option>');
                    (c.subcategories || []).forEach(function (s) {
                        subcatSelect.insertAdjacentHTML('beforeend',
                            '<option value="' + s.id + '">[' + _esc(c.name) + '] ' + _esc(s.name) + '</option>');
                    });
                });
            })
            .catch(function (err) { console.error('Error loading categories', err); });
    }

    function _load(page) {
        _currentPage = page || 1;
        var search = document.getElementById('searchInput').value.trim();
        var stockF = document.getElementById('stockFilter').value;

        var params = new URLSearchParams();
        if (search) params.set('search', search);
        if (stockF === 'low') params.set('below_restock', 'true');

        document.getElementById('productsContainer').innerHTML =
            '<div class="text-center py-5"><div class="spinner-border" style="color:var(--maint-primary);" role="status"></div></div>';

        MaintUtils.api.fetch(API + '/products?' + params.toString())
            .then(function (d) {
                _totalPages = 1; // proxy returns all, no server-side pagination for products
                _renderProducts(d.products || []);
                document.getElementById('pagination').classList.add('d-none');
            })
            .catch(function () {
                document.getElementById('productsContainer').innerHTML =
                    '<div class="alert alert-danger m-3">Error al cargar los productos.</div>';
            });
    }

    function _renderProducts(products) {
        if (!products.length) {
            document.getElementById('productsContainer').innerHTML =
                '<div class="text-center py-5 text-muted"><i class="bi bi-box-seam fs-1 d-block mb-3"></i><p>Sin productos.</p></div>';
            return;
        }
        var canAdjust = (typeof CAN_ADJUST !== 'undefined') && CAN_ADJUST;
        var rows = products.map(function (p) {
            var stock = p.total_stock != null ? p.total_stock : 0;
            var below = p.is_below_restock;
            var stockBadge = below
                ? '<span class="badge bg-danger">' + stock + '</span>'
                : '<span class="badge bg-success">' + stock + '</span>';
            var adjustBtn = canAdjust
                ? '<button class="btn btn-sm btn-outline-warning me-1" title="Ajustar stock" onclick="MaintWarehouseProducts.openAdjust(' + p.id + ', \'' + _escAttr(p.name) + '\')">' +
                  '<i class="bi bi-sliders"></i></button>'
                : '';
            return '<tr>' +
                '<td><code>' + _esc(p.code || '—') + '</code></td>' +
                '<td><strong>' + _esc(p.name) + '</strong>' +
                (p.description ? '<br><small class="text-muted">' + _esc(p.description.substring(0, 60)) + '</small>' : '') + '</td>' +
                '<td class="small">' + _esc(p.category_name || '—') + (p.subcategory_name ? ' [' + _esc(p.subcategory_name) + ']' : '') + '</td>' +
                '<td>' + stockBadge + ' <small class="text-muted">' + _esc(p.unit_of_measure || '') + '</small></td>' +
                '<td>' +
                '<button class="btn btn-sm btn-outline-secondary me-1" title="Ver lotes" onclick="MaintWarehouseProducts.showStock(' + p.id + ', \'' + _escAttr(p.name) + '\')">' +
                '<i class="bi bi-boxes"></i></button>' +
                adjustBtn +
                '<button class="btn btn-sm btn-outline-secondary" title="Editar" onclick="MaintWarehouseProducts.edit(' + p.id + ')">' +
                '<i class="bi bi-pencil"></i></button>' +
                '</td>' +
                '</tr>';
        }).join('');
        document.getElementById('productsContainer').innerHTML =
            '<div class="table-responsive">' +
            '<table class="table table-hover mb-0">' +
            '<thead class="table-light"><tr><th>Código</th><th>Nombre</th><th>Categoría</th><th>Stock</th><th></th></tr></thead>' +
            '<tbody>' + rows + '</tbody>' +
            '</table></div>';
    }

    function _reset() {
        document.getElementById('searchInput').value = '';
        document.getElementById('categoryFilter').value = '';
        document.getElementById('stockFilter').value = '';
        _load(1);
    }

    function _showStock(productId, name) {
        var body = document.getElementById('stockDetailBody');
        body.innerHTML = '<div class="text-center py-4"><div class="spinner-border" style="color:var(--maint-primary);" role="status"></div></div>';
        new bootstrap.Modal(document.getElementById('stockDetailModal')).show();

        MaintUtils.api.fetch(API + '/stock-entries?product_id=' + productId)
            .then(function (d) {
                var entries = d.entries || [];
                if (!entries.length) {
                    body.innerHTML = '<p class="text-muted text-center py-4">Sin entradas de stock.</p>';
                    return;
                }
                var rows = entries.map(function (e) {
                    var orig = parseFloat(e.quantity_original);
                    var rem = parseFloat(e.quantity_remaining);
                    var pct = orig > 0 ? Math.round((rem / orig) * 100) : 0;
                    return '<tr>' +
                        '<td><code>' + _esc(e.purchase_folio || '—') + '</code></td>' +
                        '<td>' + _esc(e.purchase_date) + '</td>' +
                        '<td>' +
                        '<div class="d-flex align-items-center gap-2">' +
                        '<div class="progress flex-grow-1" style="height:8px;min-width:50px;"><div class="progress-bar" style="width:' + pct + '%;background:var(--maint-primary);"></div></div>' +
                        '<small>' + rem + '/' + orig + '</small>' +
                        '</div></td>' +
                        '<td>$' + parseFloat(e.unit_cost || 0).toFixed(2) + '</td>' +
                        '<td>' + _esc(e.supplier || '—') + '</td>' +
                        '<td>' + (e.is_exhausted ? '<span class="badge bg-secondary">Agotado</span>' : '<span class="badge bg-success">Disponible</span>') + '</td>' +
                        '</tr>';
                }).join('');
                body.innerHTML =
                    '<h6 class="mb-3"><i class="bi bi-box-seam me-2"></i>' + _esc(name) + ' — Lotes</h6>' +
                    '<div class="table-responsive"><table class="table table-sm table-hover">' +
                    '<thead class="table-light"><tr><th>Folio</th><th>Fecha</th><th>Stock</th><th>Costo</th><th>Proveedor</th><th>Estado</th></tr></thead>' +
                    '<tbody>' + rows + '</tbody></table></div>';
            })
            .catch(function () {
                body.innerHTML = '<div class="alert alert-danger">Error al cargar stock.</div>';
            });
    }

    function _edit(productId) {
        _editingId = productId;
        document.getElementById('productModalTitle').innerHTML =
            '<i class="bi bi-pencil me-2"></i>Editar Producto';
        MaintUtils.api.fetch(API + '/products/' + productId)
            .then(function (d) {
                var p = d.product || d;
                document.getElementById('prodName').value = p.name || '';
                document.getElementById('prodUnit').value = p.unit_of_measure || '';
                document.getElementById('prodLeadTime').value = p.restock_lead_time_days || 7;
                document.getElementById('prodDesc').value = p.description || '';
                if (p.subcategory_id) document.getElementById('prodSubcategory').value = p.subcategory_id;
            })
            .catch(function (err) { console.error(err); });
        new bootstrap.Modal(document.getElementById('productModal')).show();
    }

    function _save() {
        var body = {
            name: document.getElementById('prodName').value.trim(),
            unit_of_measure: document.getElementById('prodUnit').value.trim(),
            restock_lead_time_days: parseInt(document.getElementById('prodLeadTime').value) || 7,
            subcategory_id: parseInt(document.getElementById('prodSubcategory').value) || null,
            description: document.getElementById('prodDesc').value.trim() || null,
        };
        if (!_editingId) {
            body.department_code = 'equipment_maint';
        }
        if (!body.name || !body.unit_of_measure || !body.subcategory_id) {
            MaintUtils.toast('Completa los campos obligatorios.', 'warning');
            return;
        }
        var method = _editingId ? 'PATCH' : 'POST';
        var url = _editingId ? API + '/products/' + _editingId : API + '/products';

        MaintUtils.api.fetch(url, { method: method, body: JSON.stringify(body) })
            .then(function () {
                bootstrap.Modal.getInstance(document.getElementById('productModal')).hide();
                MaintUtils.toast('Producto guardado.', 'success');
                _editingId = null;
                _load(1);
            })
            .catch(function (err) { MaintUtils.toast(err.message, 'error'); });
    }

    // === AJUSTE MANUAL DE STOCK (solo admin/jefe) ===

    function _openAdjust(productId, name) {
        var el = document.getElementById('adjustModal');
        if (!el) return; // no renderizado (usuario sin permiso)

        document.getElementById('adjustProductId').value = productId;
        document.getElementById('adjustProductName').textContent = name;
        document.getElementById('adjustTypeIn').checked = true;
        document.getElementById('adjustQuantity').value = '';
        document.getElementById('adjustNotes').value = '';
        document.getElementById('adjustJustification').value = '';
        document.getElementById('adjustNotesCount').textContent = '0 / 500';
        document.getElementById('adjustJustifCount').textContent = '0 / 1000';

        new bootstrap.Modal(el).show();
    }

    function _saveAdjust() {
        var productId = parseInt(document.getElementById('adjustProductId').value);
        var adjustType = document.querySelector('input[name="adjustType"]:checked');
        var quantity = document.getElementById('adjustQuantity').value.trim();
        var notes = document.getElementById('adjustNotes').value.trim();
        var justification = document.getElementById('adjustJustification').value.trim();

        // Validación cliente
        if (!adjustType) {
            MaintUtils.toast('Selecciona el tipo de ajuste.', 'warning');
            return;
        }
        var qty = parseFloat(quantity);
        if (!quantity || isNaN(qty) || qty <= 0) {
            MaintUtils.toast('La cantidad debe ser mayor a 0.', 'warning');
            return;
        }
        if (notes.length < 5) {
            MaintUtils.toast('Las notas deben tener al menos 5 caracteres.', 'warning');
            return;
        }
        if (justification.length < 10) {
            MaintUtils.toast('La justificación debe tener al menos 10 caracteres.', 'warning');
            return;
        }

        var btn = document.getElementById('btnAdjustSave');
        MaintUtils.loading.show(btn, 'Guardando...');

        MaintUtils.api.fetch(API + '/adjust', {
            method: 'POST',
            body: JSON.stringify({
                product_id: productId,
                quantity: qty,
                adjust_type: adjustType.value,
                notes: notes,
                justification: justification,
            }),
        })
        .then(function () {
            var modal = bootstrap.Modal.getInstance(document.getElementById('adjustModal'));
            if (modal) modal.hide();
            var typeLabel = adjustType.value === 'IN' ? 'entrada' : 'salida';
            MaintUtils.toast('Ajuste de stock (' + typeLabel + ') registrado correctamente.', 'success');
            _load(_currentPage);
        })
        .catch(function (err) {
            MaintUtils.toast(err.message || 'Error al registrar el ajuste.', 'error');
        })
        .finally(function () {
            MaintUtils.loading.hide(btn);
        });
    }

    function _esc(s) {
        var d = document.createElement('div');
        d.appendChild(document.createTextNode(String(s || '')));
        return d.innerHTML;
    }

    function _escAttr(s) {
        return String(s || '').replace(/'/g, "\\'");
    }

    document.addEventListener('DOMContentLoaded', function () {
        document.getElementById('productModal').addEventListener('hidden.bs.modal', function () {
            _editingId = null;
            document.getElementById('productId').value = '';
            document.getElementById('productModalTitle').innerHTML = '<i class="bi bi-box-seam me-2"></i>Nuevo Producto';
            document.getElementById('prodName').value = '';
            document.getElementById('prodUnit').value = '';
            document.getElementById('prodLeadTime').value = 7;
            document.getElementById('prodSubcategory').value = '';
            document.getElementById('prodDesc').value = '';
        });

        // Contadores de caracteres para el modal de ajuste (solo si existe en DOM)
        var notesInput = document.getElementById('adjustNotes');
        var justifInput = document.getElementById('adjustJustification');
        if (notesInput) {
            notesInput.addEventListener('input', function () {
                document.getElementById('adjustNotesCount').textContent = notesInput.value.length + ' / 500';
            });
        }
        if (justifInput) {
            justifInput.addEventListener('input', function () {
                document.getElementById('adjustJustifCount').textContent = justifInput.value.length + ' / 1000';
            });
        }

        _loadCategories();
        _load(1);
    });

})();
