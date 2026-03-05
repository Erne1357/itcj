// static/js/coord_home.js
(async () => {
    const $ = (s) => document.querySelector(s);
    const periodNameEl = $("#periodName");
    const kApTotal = $("#kpiApTotal");
    const kApPend = $("#kpiApPending");
    const kDrTotal = $("#kpiDropTotal");
    const kDrPend = $("#kpiDropPending");
    const remindersEl = $("#reminderList");

    async function loadDashboard() {
        try {
            const r = await fetch("/api/agendatec/v2/coord/dashboard", { credentials: "include" });
            if (!r.ok) throw 0;
            const data = await r.json();

            // Actualizar nombre del período (semestre)
            if (data?.period?.name && periodNameEl) {
                periodNameEl.textContent = data.period.name;
            }

            // KPIs
            kApTotal.textContent = data?.appointments?.total ?? "0";
            kApPend.textContent = data?.appointments?.pending ?? "0";
            kDrTotal.textContent = data?.drops?.total ?? "0";
            kDrPend.textContent = data?.drops?.pending ?? "0";

            // Recordatorios
            renderReminders(data?.missing_slots || []);

            // Suscripción a rooms de sockets (una sola vez)
            tryJoinRoomsOnce(data?.days_allowed || [], data?.current_coordinator_id);
        } catch (e) {
            console.error("[dash] error load", e);
            if (periodNameEl) {
                periodNameEl.textContent = "Error al cargar";
            }
        }
    }

    function renderReminders(missingDays) {
        if (!remindersEl) return;
        if (!missingDays.length) {
            remindersEl.innerHTML = `<div class="text-muted small">No tienes pendientes de configuración de horario.</div>`;
            return;
        }
        // Muestra hasta 5 recordatorios
        const items = missingDays.slice(0, 5).map(d => `
      <div class="d-flex align-items-center justify-content-between p-2 border rounded-3">
        <div><i class="bi bi-exclamation-triangle text-warning me-2"></i>
             <span>Falta configurar horario para <strong>${d}</strong></span></div>
        <a class="btn btn-sm btn-outline-primary" href="/agendatec/coord/slots#${d}">Configurar</a>
      </div>
    `).join("");
        remindersEl.innerHTML = items;
    }

    // ---- Sockets: refrescar KPIs cuando cambien requests ----
    let roomsBound = false;
    let _lastCoordId = 0;
    let _lastDays = [];
    const scheduleReload = debounce(() => loadDashboard(), 250);

    function joinRooms(coordId, daysAllowed) {
        window.__reqJoinDrops?.({ coord_id: coordId });
        (daysAllowed || []).forEach(day => {
            window.__reqJoinApDay?.({ coord_id: coordId, day });
        });
    }

    function tryJoinRoomsOnce(daysAllowed, coordEntityId) {
        const coordId = coordEntityId || 0;
        const s = window.__reqSocket;
        if (!coordId || !s) return;
        _lastCoordId = coordId;
        _lastDays = daysAllowed || [];
        joinRooms(coordId, daysAllowed);
        if (!roomsBound) {
            // Registrar handlers de eventos una sola vez
            s.off?.("appointment_created");
            s.off?.("drop_created");
            s.off?.("request_status_changed");
            s.on("appointment_created", () => { scheduleReload(); });
            s.on("drop_created", () => { scheduleReload(); });
            s.on("request_status_changed", () => { scheduleReload(); });
            // Al reconectarse, el servidor elimina las rooms — hay que volver a unirse
            s.on("connect", () => {
                if (_lastCoordId) joinRooms(_lastCoordId, _lastDays);
            });
            roomsBound = true;
        }
    }

    function debounce(fn, wait) {
        let t = null; return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), wait); };
    }

    // Carga inicial
    await loadDashboard();
})();
