/**
 * ticket-resolution.js — Modales de resolución y calificación de tickets
 * Expone: window.MaintResolution
 */
'use strict';

(function () {

    var API_BASE = '/api/maint/v2';
    var ctx = window.TICKET_CTX || {};

    // ── API pública ───────────────────────────────────────────────────────────

    window.MaintResolution = {
        openModal: function (ticket) {
            _openResolveModal(ticket);
        },
        openRateModal: function () {
            _openRateModal();
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
            }),
        })
            .then(function () {
                modal.hide();
                MaintUtils.toast('Ticket resuelto correctamente', 'success');
                if (window._maintDetailReload) _maintDetailReload();
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
