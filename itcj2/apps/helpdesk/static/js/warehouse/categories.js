// itcj2/apps/helpdesk/static/js/warehouse/categories.js

const WarehouseCategories = (function () {
    'use strict';

    const API = '/api/warehouse/v2';
    let selectedCatId = null;

    // Stored handler references for cleanup
    let _onCategoryModalHidden = null;
    let _onSubcategoryModalHidden = null;

    async function load() {
        try {
            const res = await fetch(`${API}/categories?with_subcategories=true`);
            const d = await res.json();
            renderCategories(d.categories || []);
        } catch (e) {
            document.getElementById('categoriesList').innerHTML =
                '<div class="alert alert-danger m-2">Error al cargar.</div>';
        }
    }

    function renderCategories(cats) {
        const list = document.getElementById('categoriesList');
        if (!cats.length) {
            list.innerHTML = '<div class="text-center py-4 text-muted small">Sin categorías</div>';
            return;
        }
        list.innerHTML = cats.map(c => `
            <a href="#" class="list-group-item list-group-item-action d-flex justify-content-between align-items-center"
               onclick="WarehouseCategories.selectCategory(${c.id}, '${c.name.replace(/'/g, "\\'")}'); return false;">
                <span><i class="fas fa-folder text-primary me-2"></i>${c.name}</span>
                <span class="badge bg-info rounded-pill">${c.subcategories?.length || 0}</span>
            </a>`).join('');
    }

    function selectCategory(id, name) {
        selectedCatId = id;
        document.getElementById('selectedCatName').textContent = name;
        document.getElementById('btnNewSubcat').disabled = false;

        document.querySelectorAll('#categoriesList .list-group-item').forEach(el => {
            el.classList.remove('active');
        });
        event.currentTarget.classList.add('active');

        loadSubcategories(id);
    }

    async function loadSubcategories(catId) {
        document.getElementById('subcategoriesList').innerHTML =
            '<div class="text-center py-4"><div class="spinner-border spinner-border-sm text-primary" role="status"></div></div>';
        try {
            const res = await fetch(`${API}/categories/${catId}/subcategories`);
            const d = await res.json();
            renderSubcategories(d.subcategories || []);
        } catch (e) {
            document.getElementById('subcategoriesList').innerHTML =
                '<div class="alert alert-danger m-3">Error al cargar subcategorías.</div>';
        }
    }

    function renderSubcategories(subs) {
        const container = document.getElementById('subcategoriesList');
        if (!subs.length) {
            container.innerHTML = '<div class="text-center py-5 text-muted">Sin subcategorías</div>';
            return;
        }
        const rows = subs.map(s => `
            <tr>
                <td>${s.name}</td>
                <td class="text-muted">${s.description || '-'}</td>
                <td>
                    <button class="btn btn-sm btn-outline-secondary"
                        onclick="WarehouseCategories.editSubcategory(${s.id}, '${s.name.replace(/'/g, "\\'")}', '${(s.description||'').replace(/'/g, "\\'")}')">
                        <i class="fas fa-edit"></i>
                    </button>
                </td>
            </tr>`).join('');
        container.innerHTML = `
            <div class="table-responsive">
                <table class="table table-hover mb-0">
                    <thead class="table-light">
                        <tr><th>Nombre</th><th>Descripción</th><th></th></tr>
                    </thead>
                    <tbody>${rows}</tbody>
                </table>
            </div>`;
    }

    async function saveCategory() {
        const id = document.getElementById('catId').value;
        const body = {
            name: document.getElementById('catName').value.trim(),
            description: document.getElementById('catDesc').value.trim() || null,
            department_code: document.getElementById('catDept').value.trim() || null,
        };
        if (!body.name) { HelpdeskUtils.showToast('El nombre es obligatorio.', 'warning'); return; }

        const method = id ? 'PATCH' : 'POST';
        const url = id ? `${API}/categories/${id}` : `${API}/categories`;

        try {
            const res = await fetch(url, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
            if (!res.ok) throw new Error((await res.json()).detail || 'Error');
            bootstrap.Modal.getInstance(document.getElementById('categoryModal')).hide();
            HelpdeskUtils.showToast('Categoría guardada.', 'success');
            load();
        } catch (err) { HelpdeskUtils.showToast(err.message, 'danger'); }
    }

    function editSubcategory(id, name, desc) {
        document.getElementById('subcatId').value = id;
        document.getElementById('subcatName').value = name;
        document.getElementById('subcatDesc').value = desc;
        new bootstrap.Modal(document.getElementById('subcategoryModal')).show();
    }

    async function saveSubcategory() {
        const id = document.getElementById('subcatId').value;
        const body = {
            name: document.getElementById('subcatName').value.trim(),
            description: document.getElementById('subcatDesc').value.trim() || null,
        };
        if (!body.name) { HelpdeskUtils.showToast('El nombre es obligatorio.', 'warning'); return; }

        const method = id ? 'PATCH' : 'POST';
        const url = id
            ? `${API}/subcategories/${id}`
            : `${API}/categories/${selectedCatId}/subcategories`;

        try {
            const res = await fetch(url, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
            if (!res.ok) throw new Error((await res.json()).detail || 'Error');
            bootstrap.Modal.getInstance(document.getElementById('subcategoryModal')).hide();
            HelpdeskUtils.showToast('Subcategoría guardada.', 'success');
            if (selectedCatId) loadSubcategories(selectedCatId);
        } catch (err) { HelpdeskUtils.showToast(err.message, 'danger'); }
    }

    function init() {
        selectedCatId = null;

        _onCategoryModalHidden = function () {
            document.getElementById('catId').value = '';
            document.getElementById('catName').value = '';
            document.getElementById('catDesc').value = '';
        };
        _onSubcategoryModalHidden = function () {
            document.getElementById('subcatId').value = '';
            document.getElementById('subcatName').value = '';
            document.getElementById('subcatDesc').value = '';
        };

        const catModal = document.getElementById('categoryModal');
        if (catModal) catModal.addEventListener('hidden.bs.modal', _onCategoryModalHidden);

        const subcatModal = document.getElementById('subcategoryModal');
        if (subcatModal) subcatModal.addEventListener('hidden.bs.modal', _onSubcategoryModalHidden);

        load();
    }

    function destroy() {
        const catModal = document.getElementById('categoryModal');
        if (catModal && _onCategoryModalHidden) {
            catModal.removeEventListener('hidden.bs.modal', _onCategoryModalHidden);
        }
        const subcatModal = document.getElementById('subcategoryModal');
        if (subcatModal && _onSubcategoryModalHidden) {
            subcatModal.removeEventListener('hidden.bs.modal', _onSubcategoryModalHidden);
        }
        _onCategoryModalHidden = null;
        _onSubcategoryModalHidden = null;
        selectedCatId = null;
    }

    window.WarehouseCategories = { selectCategory, saveCategory, editSubcategory, saveSubcategory };
    window.HelpdeskPage.page('warehouse_categories', { init: init, destroy: destroy });

    return { selectCategory, saveCategory, editSubcategory, saveSubcategory };
})();
