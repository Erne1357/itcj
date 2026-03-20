(function () {
    'use strict';

    // --- Logout buttons ---
    document.querySelectorAll('.btn-email-logout').forEach(function (btn) {
        btn.addEventListener('click', function () {
            var appKey = btn.getAttribute('data-app-key');
            if (!confirm('Desconectar correo de ' + appKey + '?')) return;

            btn.disabled = true;
            btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Desconectando...';

            fetch('/itcj/config/email/auth/logout?app=' + encodeURIComponent(appKey), {
                method: 'POST',
                credentials: 'include'
            })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.ok) {
                    updateCardDisconnected(appKey);
                    showSuccess('Correo desconectado de ' + appKey);
                } else {
                    showError(data.error || 'Error al desconectar');
                    resetLogoutBtn(btn);
                }
            })
            .catch(function () {
                // Aun si hubo error de red, verificar si realmente se desconecto
                updateCardDisconnected(appKey);
            });
        });
    });

    function resetLogoutBtn(btn) {
        btn.disabled = false;
        btn.innerHTML = '<i class="bi bi-box-arrow-right me-1"></i>Desconectar';
    }

    // --- Refresh status on load ---
    document.querySelectorAll('.email-app-card').forEach(function (card) {
        var appKey = card.getAttribute('data-app-key');
        refreshStatus(appKey);
    });

    function refreshStatus(appKey) {
        fetch('/itcj/config/email/auth/status?app=' + encodeURIComponent(appKey), {
            credentials: 'include'
        })
        .then(function (r) { return r.json(); })
        .then(function (data) {
            if (data.connected) {
                updateCardConnected(appKey, (data.account || {}).name, (data.account || {}).username);
            } else {
                updateCardDisconnected(appKey);
            }
        })
        .catch(function () { /* silently fail */ });
    }

    function updateCardConnected(appKey, name, username) {
        // Badge
        var badge = document.querySelector('.email-status-badge[data-app-key="' + appKey + '"]');
        if (badge) {
            badge.textContent = 'Conectado';
            badge.className = 'badge email-status-badge bg-success';
        }
        // Account info
        var info = document.querySelector('.email-account-info[data-app-key="' + appKey + '"]');
        if (info) {
            var html = '<div class="d-flex align-items-center gap-2 text-success">' +
                '<i class="bi bi-person-check-fill"></i><span class="small">';
            if (name) html += name + ' &mdash; ';
            html += '<strong>' + (username || '') + '</strong></span></div>';
            info.innerHTML = html;
        }
    }

    function updateCardDisconnected(appKey) {
        // Badge
        var badge = document.querySelector('.email-status-badge[data-app-key="' + appKey + '"]');
        if (badge) {
            badge.textContent = 'Sin sesion';
            badge.className = 'badge email-status-badge bg-secondary';
        }
        // Account info
        var info = document.querySelector('.email-account-info[data-app-key="' + appKey + '"]');
        if (info) {
            info.innerHTML = '<div class="d-flex align-items-center gap-2 text-muted">' +
                '<i class="bi bi-person-x"></i>' +
                '<span class="small">No hay cuenta conectada</span></div>';
        }
        // Card border
        var card = document.querySelector('.email-app-card[data-app-key="' + appKey + '"]');
        if (card) card.classList.remove('border-success');
        // Buttons - use specific selector
        var actions = document.querySelector('.email-actions[data-app-key="' + appKey + '"]');
        if (actions) {
            actions.innerHTML =
                '<a href="/itcj/config/email/auth/login?app=' + encodeURIComponent(appKey) + '" ' +
                'class="btn btn-sm btn-primary">' +
                '<i class="bi bi-microsoft me-1"></i>Conectar</a>';
        }
    }
})();
