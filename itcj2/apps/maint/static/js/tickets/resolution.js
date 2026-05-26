/**
 * ticket-resolution.js — Modales de resolución y calificación de tickets
 * Expone: window.MaintResolution
 */
'use strict';

(function () {

    var API_BASE = '/api/maint/v2';
    var ctx = window.TICKET_CTX || {};

    // ── Estado de materiales ──────────────────────────────────────────────────

    var _materialsMap = {};  // product_id → {product_id, name, unit, quantity, notes}
    var _searchTimeout = null;
    var _resolutionFiles = [];   // FileList materializado en array

    var MAX_RESOLUTION_FILES = 5;
    var MAX_IMAGE_BYTES = 3 * 1024 * 1024;
    var MAX_PDF_BYTES = 10 * 1024 * 1024;

    // ── API pública ───────────────────────────────────────────────────────────

    window.MaintResolution = {
        openModal: function (ticket) {
            _openResolveModal(ticket);
        },
        openRateModal: function () {
            _openRateModal();
        },
        removeMaterial: function (productId) {
            delete _materialsMap[productId];
            _renderMaterialsList();
        },
        _updateQty: function (productId, val) {
            if (_materialsMap[productId]) {
                _materialsMap[productId].quantity = parseFloat(val) || 1;
            }
        },
        _updateNotes: function (productId, val) {
            if (_materialsMap[productId]) {
                _materialsMap[productId].notes = val;
            }
        },
    };

    // ── Modal: Resolver ───────────────────────────────────────────────────────

    function _openResolveModal(ticket) {
        var modalEl = document.getElementById('resolveModal');
        var modal = new bootstrap.Modal(modalEl);

        // Reset form
        document.querySelector('input[name="resolveOutcome"][value="true"]').checked = true;
        document.getElementById('maintenanceType').value = '';
        document.getElementById('serviceOrigin').value = '';
        document.getElementById('resolutionNotes').value = '';
        document.getElementById('timeInvested').value = '';
        document.getElementById('resolutionObservations').value = '';

        // Reset materials
        _materialsMap = {};
        _renderMaterialsList();

        // Reset adjuntos de resolución
        _resolutionFiles = [];
        _renderResolutionFilesList();
        var fileInput = document.getElementById('resolutionFiles');
        if (fileInput) {
            fileInput.value = '';
            fileInput.onchange = function () {
                _addResolutionFiles(fileInput.files);
                fileInput.value = '';
            };
        }
        var searchInput = document.getElementById('materialSearchInput');
        if (searchInput) {
            searchInput.value = '';
            searchInput.oninput = function () {
                clearTimeout(_searchTimeout);
                var q = searchInput.value.trim();
                if (q.length < 2) {
                    _hideSearchResults();
                    return;
                }
                _searchTimeout = setTimeout(function () { _searchProducts(q); }, 300);
            };
            searchInput.addEventListener('blur', function () {
                setTimeout(_hideSearchResults, 200);
            });
        }

        // Remove previous is-invalid states
        ['maintenanceType', 'serviceOrigin', 'resolutionNotes', 'timeInvested'].forEach(function (id) {
            var el = document.getElementById(id);
            if (el) el.classList.remove('is-invalid');
        });

        modal.show();

        document.getElementById('confirmResolveBtn').onclick = function () {
            _submitResolve(modal);
        };
    }

    function _searchProducts(query) {
        MaintUtils.api.fetch(
            API_BASE + '/tickets/warehouse-products?search=' + encodeURIComponent(query) + '&limit=15'
        ).then(function (data) {
            _showSearchResults(data.products || []);
        }).catch(function () {
            _hideSearchResults();
        });
    }

    function _showSearchResults(products) {
        var container = document.getElementById('materialSearchResults');
        if (!container) return;

        if (!products.length) {
            container.style.display = 'none';
            return;
        }

        container.innerHTML = '';
        products.forEach(function (p) {
            var item = document.createElement('button');
            item.type = 'button';
            item.className = 'list-group-item list-group-item-action py-1 px-2 small';
            item.innerHTML =
                '<span class="fw-medium">' + _esc(p.name) + '</span>' +
                '<span class="text-muted ms-2">' + _esc(p.unit_of_measure || '') + '</span>' +
                (p.total_stock !== undefined
                    ? '<span class="badge bg-light text-secondary ms-auto float-end">' + p.total_stock + ' disp.</span>'
                    : '');
            item.onclick = function () {
                _addMaterial(p);
                document.getElementById('materialSearchInput').value = '';
                _hideSearchResults();
            };
            container.appendChild(item);
        });
        container.style.display = 'block';
    }

    function _hideSearchResults() {
        var container = document.getElementById('materialSearchResults');
        if (container) container.style.display = 'none';
    }

    function _addMaterial(product) {
        var id = product.id || product.product_id;
        if (!_materialsMap[id]) {
            _materialsMap[id] = {
                product_id: id,
                name: product.name,
                unit: product.unit_of_measure || '',
                quantity: 1,
                notes: '',
            };
        }
        _renderMaterialsList();
    }

    function _renderMaterialsList() {
        var container = document.getElementById('materialsList');
        if (!container) return;

        var keys = Object.keys(_materialsMap);
        if (!keys.length) {
            container.innerHTML = '<span class="text-muted small">Sin materiales agregados.</span>';
            return;
        }

        container.innerHTML = '';
        keys.forEach(function (pid) {
            var mat = _materialsMap[pid];
            var row = document.createElement('div');
            row.className = 'd-flex align-items-center gap-2 p-2 border rounded bg-light';
            row.innerHTML =
                '<div class="flex-grow-1 small fw-medium text-truncate" title="' + _esc(mat.name) + '">' + _esc(mat.name) + '</div>' +
                '<input type="number" min="0.01" step="0.01" class="form-control form-control-sm" style="width:80px;"' +
                '  value="' + mat.quantity + '"' +
                '  onchange="MaintResolution._updateQty(' + pid + ', this.value)">' +
                '<span class="small text-muted">' + _esc(mat.unit) + '</span>' +
                '<input type="text" class="form-control form-control-sm" style="width:120px;" placeholder="Notas"' +
                '  value="' + _esc(mat.notes) + '"' +
                '  oninput="MaintResolution._updateNotes(' + pid + ', this.value)">' +
                '<button type="button" class="btn btn-outline-danger btn-sm py-0 px-1"' +
                '  onclick="MaintResolution.removeMaterial(' + pid + ')">' +
                '  <i class="bi bi-x"></i>' +
                '</button>';
            container.appendChild(row);
        });
    }

    // ── Adjuntos de resolución ────────────────────────────────────────────────

    function _addResolutionFiles(fileList) {
        if (!fileList) return;
        for (var i = 0; i < fileList.length; i++) {
            if (_resolutionFiles.length >= MAX_RESOLUTION_FILES) {
                MaintUtils.toast('Máximo ' + MAX_RESOLUTION_FILES + ' archivos de evidencia', 'warning');
                break;
            }
            var f = fileList[i];
            var isPdf = f.type === 'application/pdf';
            var isImg = f.type.indexOf('image/') === 0;
            if (!isPdf && !isImg) {
                MaintUtils.toast('Tipo no permitido: ' + f.name, 'warning');
                continue;
            }
            var maxBytes = isPdf ? MAX_PDF_BYTES : MAX_IMAGE_BYTES;
            if (f.size > maxBytes) {
                MaintUtils.toast(f.name + ' excede el tamaño permitido', 'warning');
                continue;
            }
            _resolutionFiles.push(f);
        }
        _renderResolutionFilesList();
    }

    window.MaintResolution.removeResolutionFile = function (idx) {
        _resolutionFiles.splice(idx, 1);
        _renderResolutionFilesList();
    };

    function _renderResolutionFilesList() {
        var container = document.getElementById('resolutionFilesList');
        if (!container) return;
        if (!_resolutionFiles.length) {
            container.innerHTML = '<span class="text-muted small">Sin archivos.</span>';
            return;
        }
        container.innerHTML = '';
        _resolutionFiles.forEach(function (f, idx) {
            var isPdf = f.type === 'application/pdf';
            var icon = isPdf ? 'bi-file-earmark-pdf text-danger' : 'bi-image text-primary';
            var row = document.createElement('div');
            row.className = 'd-flex align-items-center gap-2 p-1 px-2 border rounded bg-light small';
            row.innerHTML =
                '<i class="bi ' + icon + '"></i>' +
                '<span class="flex-grow-1 text-truncate" title="' + _esc(f.name) + '">' + _esc(f.name) + '</span>' +
                '<span class="text-muted">' + (Math.round(f.size / 1024)) + ' KB</span>' +
                '<button type="button" class="btn btn-outline-danger btn-sm py-0 px-1"' +
                '  onclick="MaintResolution.removeResolutionFile(' + idx + ')">' +
                '  <i class="bi bi-x"></i></button>';
            container.appendChild(row);
        });
    }

    function _uploadResolutionAttachments(ticketId) {
        if (!_resolutionFiles.length) return Promise.resolve([]);
        var url = API_BASE + '/tickets/' + ticketId + '/attachments';
        var promises = _resolutionFiles.map(function (file) {
            var fd = new FormData();
            fd.append('file', file);
            fd.append('attachment_type', 'resolution');
            return fetch(url, { method: 'POST', credentials: 'include', body: fd })
                .then(function (r) {
                    if (!r.ok) throw new Error('upload_failed');
                    return r.json();
                })
                .catch(function () { return { error: file.name }; });
        });
        return Promise.all(promises);
    }

    function _submitResolve(modal) {
        var btn = document.getElementById('confirmResolveBtn');
        var valid = true;

        var outcomeVal = document.querySelector('input[name="resolveOutcome"]:checked');
        var success = outcomeVal ? outcomeVal.value === 'true' : true;

        var maintenanceType = document.getElementById('maintenanceType').value;
        var serviceOrigin = document.getElementById('serviceOrigin').value;
        var resolutionNotes = document.getElementById('resolutionNotes').value.trim();
        var timeInvestedStr = document.getElementById('timeInvested').value;
        var timeInvested = parseInt(timeInvestedStr, 10);
        var observations = document.getElementById('resolutionObservations').value.trim();

        _setInvalid('maintenanceType', !maintenanceType);
        _setInvalid('serviceOrigin', !serviceOrigin);
        _setInvalid('resolutionNotes', resolutionNotes.length < 10);
        _setInvalid('timeInvested', !timeInvestedStr || isNaN(timeInvested) || timeInvested < 1);

        if (!maintenanceType || !serviceOrigin || resolutionNotes.length < 10 ||
            !timeInvestedStr || isNaN(timeInvested) || timeInvested < 1) {
            valid = false;
        }

        if (!valid) {
            MaintUtils.toast('Completa todos los campos requeridos', 'warning');
            return;
        }

        var materialsUsed = Object.values(_materialsMap).map(function (m) {
            return {
                product_id: m.product_id,
                quantity: m.quantity,
                notes: m.notes || null,
            };
        });

        MaintUtils.loading.show(btn, 'Resolviendo...');

        MaintUtils.api.fetch(API_BASE + '/tickets/' + ctx.ticketId + '/resolve', {
            method: 'POST',
            body: JSON.stringify({
                success: success,
                maintenance_type: maintenanceType,
                service_origin: serviceOrigin,
                resolution_notes: resolutionNotes,
                time_invested_minutes: timeInvested,
                observations: observations || null,
                materials_used: materialsUsed.length ? materialsUsed : null,
            }),
        })
            .then(function (data) {
                return _uploadResolutionAttachments(ctx.ticketId).then(function (results) {
                    var failed = (results || []).filter(function (r) { return r && r.error; });
                    modal.hide();
                    var msg = 'Ticket resuelto correctamente';
                    var lvl = 'success';
                    if (data.warnings && data.warnings.length) {
                        msg = 'Ticket resuelto. Advertencias de almacén: ' + data.warnings.join('; ');
                        lvl = 'warning';
                    }
                    if (failed.length) {
                        msg += ' (no se subieron: ' + failed.map(function (f) { return f.error; }).join(', ') + ')';
                        lvl = 'warning';
                    }
                    MaintUtils.toast(msg, lvl);
                    if (window._maintDetailReload) _maintDetailReload();
                });
            })
            .catch(function (err) {
                MaintUtils.loading.hide(btn);
                MaintUtils.toast(err.message, 'error');
            });
    }

    // ── Modal: Calificar ──────────────────────────────────────────────────────

    function _openRateModal() {
        var modalEl = document.getElementById('rateModal');
        var modal = new bootstrap.Modal(modalEl);

        // Reset stars
        _initStars('starsAttention', 'ratingAttention');
        _initStars('starsSpeed', 'ratingSpeed');

        // Reset other fields
        document.getElementById('effYes').checked = true;
        document.getElementById('ratingComment').value = '';

        modal.show();

        document.getElementById('confirmRateBtn').onclick = function () {
            _submitRate(modal);
        };
    }

    function _initStars(containerId, inputId) {
        var container = document.getElementById(containerId);
        var input = document.getElementById(inputId);

        input.value = '0';
        container.removeAttribute('data-value');
        container.innerHTML = '';

        for (var i = 1; i <= 5; i++) {
            var star = document.createElement('span');
            star.className = 'mn-star bi bi-star-fill';
            star.dataset.value = i;
            container.appendChild(star);
        }

        _bindStarEvents(container, input);
    }

    function _bindStarEvents(container, input) {
        var stars = container.querySelectorAll('.mn-star');

        stars.forEach(function (star) {
            star.addEventListener('click', function () {
                var val = parseInt(star.dataset.value, 10);
                input.value = val;
                container.dataset.value = val;
                _updateStarDisplay(container, val);
            });

            star.addEventListener('mouseenter', function () {
                var val = parseInt(star.dataset.value, 10);
                _updateStarDisplay(container, val);
            });
        });

        container.addEventListener('mouseleave', function () {
            var current = parseInt(input.value, 10) || 0;
            _updateStarDisplay(container, current);
        });
    }

    function _updateStarDisplay(container, value) {
        var stars = container.querySelectorAll('.mn-star');
        stars.forEach(function (s) {
            var v = parseInt(s.dataset.value, 10);
            if (v <= value) {
                s.classList.add('filled');
            } else {
                s.classList.remove('filled');
            }
        });
    }

    function _submitRate(modal) {
        var btn = document.getElementById('confirmRateBtn');

        var attentionVal = parseInt(document.getElementById('ratingAttention').value, 10);
        var speedVal = parseInt(document.getElementById('ratingSpeed').value, 10);

        if (!attentionVal || attentionVal < 1) {
            MaintUtils.toast('Califica la atención del técnico', 'warning');
            return;
        }
        if (!speedVal || speedVal < 1) {
            MaintUtils.toast('Califica la rapidez de respuesta', 'warning');
            return;
        }

        var efficiencyEl = document.querySelector('input[name="efficiencyRating"]:checked');
        var efficiency = efficiencyEl ? efficiencyEl.value === 'true' : true;
        var comment = document.getElementById('ratingComment').value.trim();

        MaintUtils.loading.show(btn, 'Enviando...');

        MaintUtils.api.fetch(API_BASE + '/tickets/' + ctx.ticketId + '/rate', {
            method: 'POST',
            body: JSON.stringify({
                rating_attention: attentionVal,
                rating_speed: speedVal,
                rating_efficiency: efficiency,
                comment: comment || null,
            }),
        })
            .then(function () {
                modal.hide();
                MaintUtils.toast('Calificación enviada. ¡Gracias!', 'success');
                if (window._maintDetailReload) _maintDetailReload();
            })
            .catch(function (err) {
                MaintUtils.loading.hide(btn);
                MaintUtils.toast(err.message, 'error');
            });
    }

    // ── Helpers ───────────────────────────────────────────────────────────────

    function _esc(str) {
        return String(str || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function _setInvalid(id, isInvalid) {
        var el = document.getElementById(id);
        if (!el) return;
        if (isInvalid) {
            el.classList.add('is-invalid');
            el.addEventListener('input', function () { el.classList.remove('is-invalid'); }, { once: true });
            el.addEventListener('change', function () { el.classList.remove('is-invalid'); }, { once: true });
        } else {
            el.classList.remove('is-invalid');
        }
    }

})();
