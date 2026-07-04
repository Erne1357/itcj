/* =============================================================================
   Correo por app — módulo del registry ConfigPage (C2).
   IIFE + register: init() re-vincula los botones de logout y refresca estado en
   cada visita (bajo morph los nodos se recrean); destroy() quita los listeners.
   Consume la API C3 de F1a (/api/core/v2/email/{status,logout}) con envelope
   {"success": true}. Confirmación con AppModal.confirm; toasts/escape via
   ConfigUtils.
   ============================================================================= */
(function () {
    'use strict';

    var API = '/api/core/v2';
    var bound = [];   // {el, handler} para desvincular en destroy

    function esc(v) { return window.ConfigUtils ? ConfigUtils.escapeHtml(v) : String(v == null ? '' : v); }
    function toast(msg, type) { if (window.ConfigUtils) ConfigUtils.showToast(msg, type || 'success'); }

    function resetLogoutBtn(btn) {
        btn.disabled = false;
        btn.innerHTML = '<i class="bi bi-box-arrow-right me-1"></i>Desconectar';
    }

    function makeLogoutHandler(btn) {
        return async function () {
            var appKey = btn.getAttribute('data-app-key');
            var ok = await AppModal.confirm({
                title: 'Desconectar correo',
                message: 'Desconectar correo de <strong>' + esc(appKey) + '</strong>?',
                html: true,
                confirmText: 'Desconectar',
                confirmVariant: 'danger',
                variant: 'warning',
            });
            if (!ok) return;

            btn.disabled = true;
            btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Desconectando...';
            try {
                var r = await fetch(API + '/email/logout?app=' + encodeURIComponent(appKey), {
                    method: 'POST', credentials: 'include',
                });
                var data = await r.json();
                if (r.ok && data.success) {
                    updateCardDisconnected(appKey);
                    toast('Correo desconectado de ' + appKey);
                } else {
                    toast(data.error || 'Error al desconectar', 'error');
                    resetLogoutBtn(btn);
                }
            } catch (e) {
                // Aun con error de red, refleja el estado desconectado
                updateCardDisconnected(appKey);
            }
        };
    }

    function refreshStatus(appKey) {
        fetch(API + '/email/status?app=' + encodeURIComponent(appKey), { credentials: 'include' })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                var st = (data && data.data) || {};
                if (st.connected) {
                    updateCardConnected(appKey, (st.account || {}).name, (st.account || {}).username);
                } else {
                    updateCardDisconnected(appKey);
                }
            })
            .catch(function () { /* silently fail */ });
    }

    function updateCardConnected(appKey, name, username) {
        var badge = document.querySelector('.email-status-badge[data-app-key="' + appKey + '"]');
        if (badge) { badge.textContent = 'Conectado'; badge.className = 'badge email-status-badge bg-success'; }
        var info = document.querySelector('.email-account-info[data-app-key="' + appKey + '"]');
        if (info) {
            var html = '<div class="d-flex align-items-center gap-2 text-success">'
                + '<i class="bi bi-person-check-fill"></i><span class="small">';
            if (name) html += esc(name) + ' &mdash; ';
            html += '<strong>' + esc(username || '') + '</strong></span></div>';
            info.innerHTML = html;
        }
    }

    function updateCardDisconnected(appKey) {
        var badge = document.querySelector('.email-status-badge[data-app-key="' + appKey + '"]');
        if (badge) { badge.textContent = 'Sin sesion'; badge.className = 'badge email-status-badge bg-secondary'; }
        var info = document.querySelector('.email-account-info[data-app-key="' + appKey + '"]');
        if (info) {
            info.innerHTML = '<div class="d-flex align-items-center gap-2 text-muted">'
                + '<i class="bi bi-person-x"></i><span class="small">No hay cuenta conectada</span></div>';
        }
        var card = document.querySelector('.email-app-card[data-app-key="' + appKey + '"]');
        if (card) card.classList.remove('border-success');
        var actions = document.querySelector('.email-actions[data-app-key="' + appKey + '"]');
        if (actions) {
            actions.innerHTML = '<a href="/itcj/config/email/auth/login?app=' + encodeURIComponent(appKey) + '" '
                + 'class="btn btn-sm btn-primary"><i class="bi bi-microsoft me-1"></i>Conectar</a>';
        }
    }

    function init() {
        var buttons = document.querySelectorAll('.btn-email-logout');
        if (!buttons.length && !document.querySelector('.email-app-card')) return;  // no es la página email
        buttons.forEach(function (btn) {
            var h = makeLogoutHandler(btn);
            btn.addEventListener('click', h);
            bound.push({ el: btn, handler: h });
        });
        document.querySelectorAll('.email-app-card').forEach(function (card) {
            refreshStatus(card.getAttribute('data-app-key'));
        });
    }

    function destroy() {
        bound.forEach(function (b) { b.el.removeEventListener('click', b.handler); });
        bound = [];
    }

    if (window.ConfigPage) {
        window.ConfigPage.register('email', { init: init, destroy: destroy });
    }
})();
