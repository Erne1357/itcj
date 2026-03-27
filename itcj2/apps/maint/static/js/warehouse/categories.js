/**
 * warehouse/categories.js — Gestión de categorías del almacén de mantenimiento
 */
'use strict';

(function () {

    var API = '/api/maint/v2/warehouse';
    var _selectedCatId = null;

    window.MaintWarehouseCategories = {
        selectCategory: function (id, name) { _selectCategory(id, name); },
        saveCategory: function () { _saveCategory(); },
        editSubcategory: function (id, name, desc) { _editSubcategory(id, name, desc); },
        saveSubcategory: function () { _saveSubcategory(); },
    };

    function _load() {
        MaintUtils.api.fetch(API + '/categories?with_subcategories=true')
            .then(function (d) { _renderCategories(d.categories || []); })
            .catch(function () {
                document.getElementById('categoriesList').innerHTML =
                    '<div class="alert alert-danger m-2">Error al cargar.</div>';
            });
    }

    function _renderCategories(cats) {
        var list = document.getElementById('categoriesList');
        if (!cats.length) {
            list.innerHTML = '<div class="text-center py-4 text-muted small">Sin categorías</div>';
            return;
        }
        list.innerHTML = cats.map(function (c) {
            return '<a href="#" class="list-group-item list-group-item-action d-flex justify-content-between align-items-center"' +
                ' onclick="MaintWarehouseCategories.selectCategory(' + c.id + ', \'' + _escAttr(c.name) + '\'); return false;">' +
                '<span><i class="bi bi-folder me-2" style="color:var(--maint-primary);"></i>' + _esc(c.name) + '</span>' +
                '<span class="badge rounded-pill" style="background:var(--maint-primary);">' + (c.subcategories ? c.subcategories.length : 0) + '</span>' +
                '</a>';
        }).join('');
    }

    function _selectCategory(id, name) {
        _selectedCatId = id;
        document.getElementById('selectedCatName').textContent = name;
        document.getElementById('btnNewSubcat').disabled = false;
        document.querySelectorAll('#categoriesList .list-group-item').forEach(function (el) {
            el.classList.remove('active');
        });
        if (event && event.currentTarget) event.currentTarget.classList.add('active');
        _loadSubcategories(id);
    }

    function _loadSubcategories(catId) {
        var container = document.getElementById('subcategoriesList');
        container.innerHTML = '<div class="text-center py-4"><div class="spinner-border spinner-border-sm" style="color:var(--maint-primary);" role="status"></div></div>';
        MaintUtils.api.fetch(API + '/categories/' + catId + '/subcategories')
            .then(function (d) { _renderSubcategories(d.subcategories || []); })
            .catch(function () {
                document.getElementById('subcategoriesList').innerHTML =
                    '<div class="alert alert-danger m-3">Error al cargar.</div>';
            });
    }

    function _renderSubcategories(subs) {
        var container = document.getElementById('subcategoriesList');
        if (!subs.length) {
            container.innerHTML = '<div class="text-center py-5 text-muted">Sin subcategorías</div>';
            return;
        }
        var rows = subs.map(function (s) {
            return '<tr>' +
                '<td>' + _esc(s.name) + '</td>' +
                '<td class="text-muted">' + _esc(s.description || '—') + '</td>' +
                '<td><button class="btn btn-sm btn-outline-secondary"' +
                ' onclick="MaintWarehouseCategories.editSubcategory(' + s.id + ', \'' + _escAttr(s.name) + '\', \'' + _escAttr(s.description || '') + '\')">' +
                '<i class="bi bi-pencil"></i></button></td>' +
                '</tr>';
        }).join('');
        container.innerHTML =
            '<div class="table-responsive"><table class="table table-hover mb-0">' +
            '<thead class="table-light"><tr><th>Nombre</th><th>Descripción</th><th></th></tr></thead>' +
            '<tbody>' + rows + '</tbody></table></div>';
    }

    function _saveCategory() {
        var id = document.getElementById('catId').value;
        var body = {
            name: document.getElementById('catName').value.trim(),
            description: document.getElementById('catDesc').value.trim() || null,
        };
        if (!body.name) { MaintUtils.toast('El nombre es obligatorio.', 'warning'); return; }

        var method = id ? 'PATCH' : 'POST';
        var url = id ? API + '/categories/' + id : API + '/categories';

        MaintUtils.api.fetch(url, { method: method, body: JSON.stringify(body) })
            .then(function () {
                bootstrap.Modal.getInstance(document.getElementById('categoryModal')).hide();
                MaintUtils.toast('Categoría guardada.', 'success');
                _load();
            })
            .catch(function (err) { MaintUtils.toast(err.message, 'error'); });
    }

    function _editSubcategory(id, name, desc) {
        document.getElementById('subcatId').value = id;
        document.getElementById('subcatName').value = name;
        document.getElementById('subcatDesc').value = desc;
        new bootstrap.Modal(document.getElementById('subcategoryModal')).show();
    }

    function _saveSubcategory() {
        var id = document.getElementById('subcatId').value;
        var body = {
            name: document.getElementById('subcatName').value.trim(),
            description: document.getElementById('subcatDesc').value.trim() || null,
        };
        if (!body.name) { MaintUtils.toast('El nombre es obligatorio.', 'warning'); return; }

        var method = id ? 'PATCH' : 'POST';
        var url = id ? API + '/subcategories/' + id : API + '/categories/' + _selectedCatId + '/subcategories';

        MaintUtils.api.fetch(url, { method: method, body: JSON.stringify(body) })
            .then(function () {
                bootstrap.Modal.getInstance(document.getElementById('subcategoryModal')).hide();
                MaintUtils.toast('Subcategoría guardada.', 'success');
                if (_selectedCatId) _loadSubcategories(_selectedCatId);
            })
            .catch(function (err) { MaintUtils.toast(err.message, 'error'); });
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
        document.getElementById('categoryModal').addEventListener('hidden.bs.modal', function () {
            document.getElementById('catId').value = '';
            document.getElementById('catName').value = '';
            document.getElementById('catDesc').value = '';
        });
        document.getElementById('subcategoryModal').addEventListener('hidden.bs.modal', function () {
            document.getElementById('subcatId').value = '';
            document.getElementById('subcatName').value = '';
            document.getElementById('subcatDesc').value = '';
        });
        _load();
    });

})();
