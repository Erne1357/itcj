// itcj2/apps/helpdesk/static/js/user/warehouse_ticket.js
// TicketWarehouse module for user ticket_detail — search, select and consume warehouse materials

const TicketWarehouse = (function () {
    'use strict';

    const API_W = '/api/warehouse/v2';
    let materials = [];
    let searchTimer = null;

    function searchProducts(query) {
        clearTimeout(searchTimer);
        const sugg = document.getElementById('warehouseProductSuggestions');
        if (!query || query.length < 2) { sugg.style.display = 'none'; return; }
        searchTimer = setTimeout(async () => {
            try {
                const res = await fetch(`${API_W}/products/available?search=${encodeURIComponent(query)}&limit=8`);
                const d = await res.json();
                renderSuggestions(d.products || []);
            } catch (e) { sugg.style.display = 'none'; }
        }, 250);
    }

    function renderSuggestions(products) {
        const sugg = document.getElementById('warehouseProductSuggestions');
        if (!products.length) { sugg.style.display = 'none'; return; }
        sugg.innerHTML = products.map(p => `
            <a href="#" class="list-group-item list-group-item-action py-1 px-2 small"
               onclick="TicketWarehouse.selectProduct(${p.id}, '${(p.code||'').replace(/'/g,"\\'")}', '${p.name.replace(/'/g,"\\'")}', '${(p.unit_of_measure||'').replace(/'/g,"\\'")}', ${p.total_stock||0}); return false;">
                <span class="badge bg-secondary me-1">${p.code || 'N/A'}</span>
                ${p.name}
                <small class="text-muted ms-1">[${p.total_stock||0} ${p.unit_of_measure||''}]</small>
            </a>`).join('');
        sugg.style.display = 'block';
    }

    let _pendingProduct = null;

    function selectProduct(id, code, name, unit, stock) {
        document.getElementById('warehouseProductSearch').value = '';
        document.getElementById('warehouseProductSuggestions').style.display = 'none';

        _pendingProduct = { id, code, name, unit, stock };
        document.getElementById('warehouseQtyProductName').textContent = `"${name}"`;
        document.getElementById('warehouseQtyHelp').textContent = `Disponible: ${stock} ${unit}`;
        document.getElementById('warehouseQtyInput').value = '';
        document.getElementById('warehouseQtyInput').max = stock;

        const modal = new bootstrap.Modal(document.getElementById('warehouseQtyModal'));
        modal.show();
        document.getElementById('warehouseQtyModal').addEventListener('shown.bs.modal', function () {
            document.getElementById('warehouseQtyInput').focus();
        }, { once: true });
    }

    function _confirmQty() {
        const p = _pendingProduct;
        if (!p) return;
        const qty = parseFloat(document.getElementById('warehouseQtyInput').value);
        if (!qty || isNaN(qty) || qty <= 0) {
            HelpdeskUtils.showToast('Ingresa una cantidad válida.', 'warning');
            return;
        }
        if (qty > p.stock) {
            HelpdeskUtils.showToast(`Stock insuficiente. Solo hay ${p.stock} ${p.unit} disponibles.`, 'warning');
            return;
        }
        bootstrap.Modal.getInstance(document.getElementById('warehouseQtyModal')).hide();
        const existing = materials.find(m => m.product_id === p.id);
        if (existing) {
            existing.quantity += qty;
        } else {
            materials.push({ product_id: p.id, product_code: p.code, product_name: p.name, unit_of_measure: p.unit, quantity: qty });
        }
        _pendingProduct = null;
        renderMaterials();
    }

    document.getElementById('warehouseQtyConfirm').addEventListener('click', _confirmQty);
    document.getElementById('warehouseQtyInput').addEventListener('keydown', function (e) {
        if (e.key === 'Enter') _confirmQty();
    });

    function removeMaterial(productId) {
        materials = materials.filter(m => m.product_id !== productId);
        renderMaterials();
    }

    function renderMaterials() {
        const list = document.getElementById('warehouseMaterialsList');
        if (!list) return;
        if (!materials.length) {
            list.innerHTML = '<div class="text-center text-muted py-2 small" id="noMaterialsMsg"><i class="fas fa-plus-circle me-1"></i>Sin materiales agregados</div>';
            return;
        }
        list.innerHTML = materials.map(m => `
            <div class="d-flex justify-content-between align-items-center py-1 border-bottom">
                <div>
                    <span class="badge bg-primary me-1">${m.product_code||'N/A'}</span>
                    <span class="small">${m.product_name}</span>
                </div>
                <div class="d-flex align-items-center gap-2">
                    <span class="badge bg-light text-dark border">${m.quantity} ${m.unit_of_measure}</span>
                    <button class="btn btn-sm btn-outline-danger py-0" onclick="TicketWarehouse.removeMaterial(${m.product_id})">
                        <i class="fas fa-times"></i>
                    </button>
                </div>
            </div>`).join('');
    }

    async function consumeAll(ticketId) {
        if (!materials.length) return true;
        for (const m of materials) {
            try {
                const res = await fetch(`${API_W}/consume`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        product_id: m.product_id,
                        quantity: m.quantity,
                        source_app: 'helpdesk',
                        source_ticket_id: ticketId,
                        notes: 'Consumo al resolver ticket',
                    }),
                });
                if (!res.ok) {
                    const err = await res.json();
                    const msg = err.detail?.message || err.detail || 'Error';
                    HelpdeskUtils.showToast(`Advertencia almacen: ${m.product_name} - ${msg}`, 'warning');
                }
            } catch (e) {
                console.error('Warehouse consume error:', e);
            }
        }
        materials = [];
        return true;
    }

    function getMaterials() { return [...materials]; }
    function reset() { materials = []; renderMaterials(); }

    return { searchProducts, selectProduct, removeMaterial, consumeAll, getMaterials, reset };
})();
