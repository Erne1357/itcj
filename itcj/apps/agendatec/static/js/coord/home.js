// static/js/coord_home.js
(async () => {
    const modalEl = document.getElementById("forcePwModal");
    const newPw = document.getElementById("newPw");
    const btnSave = document.getElementById("btnSavePw");
    const pwErr = document.getElementById("pwErr");

    const modal = new bootstrap.Modal(modalEl, { backdrop: "static", keyboard: false });

    try {
        const r = await fetch("/api/agendatec/v1/coord/password-state", { credentials: "include" });
        if (r.ok) {
            const { must_change } = await r.json();
            console.log("Must change: " + must_change);
            if (must_change) modal.show();
        }
    } catch { }

    btnSave.addEventListener("click", async () => {
        const v = (newPw.value || "").trim();
        if (!/^\d{4}$/.test(v)) {
            pwErr.classList.remove("d-none");
            return;
        }
        pwErr.classList.add("d-none");
        btnSave.disabled = true;

        try {
            const res = await fetch("/api/agendatec/v1/coord/change_password", {
                method: "POST",
                credentials: "include",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ new_password: v })
            });
            if (!res.ok) throw 0;
            showToast("Contraseña actualizada.", "success");
            modal.hide();
            // Empuja al flujo de slots si así lo quieres:
            // window.location.href = "/coord/slots";
        } catch {
            showToast("No se pudo actualizar el NIP.", "error");
        } finally {
            btnSave.disabled = false;
            newPw.value = "";
        }
    });
    const $ = (s) => document.querySelector(s);
    const kApTotal = $("#kpiApTotal");
    const kApPend = $("#kpiApPending");
    const kDrTotal = $("#kpiDropTotal");
    const kDrPend = $("#kpiDropPending");
    const remindersEl = $("#reminderList");

    async function loadDashboard() {
        try {
            const r = await fetch("/api/agendatec/v1/coord/dashboard", { credentials: "include" });
            if (!r.ok) throw 0;
            const data = await r.json();
            // KPIs
            kApTotal.textContent = data?.appointments?.total ?? "0";
            kApPend.textContent = data?.appointments?.pending ?? "0";
            kDrTotal.textContent = data?.drops?.total ?? "0";
            kDrPend.textContent = data?.drops?.pending ?? "0";
            // Recordatorios
            renderReminders(data?.missing_slots || []);
            // Suscripción a rooms de sockets (una sola vez)
            tryJoinRoomsOnce(data?.days_allowed || []);
        } catch (e) {
            console.error("[dash] error load", e);
        }
    }

    function renderReminders(missingDays) {
        if (!remindersEl) return;
        if (!missingDays.length) {
            remindersEl.innerHTML = `<div class="text-muted small">No tienes pendientes de configuración de horario.</div>`;
            return;
        }
        // Muestra hasta 3 recordatorios
        const items = missingDays.slice(0, 3).map(d => `
      <div class="d-flex align-items-center justify-content-between p-2 border rounded-3">
        <div><i class="bi bi-exclamation-triangle text-warning me-2"></i>
             <span>Falta configurar horario para <strong>${d}</strong></span></div>
        <a class="btn btn-sm btn-outline-primary" href="/coord/slots#${d}">Configurar</a>
      </div>
    `).join("");
        remindersEl.innerHTML = items;
    }

    // ---- Sockets: refrescar KPIs cuando cambien requests ----
    let roomsBound = false;
    function getCoordId() { try { return Number(document.body?.dataset?.coordId || 0); } catch { return 0; } }
    function tryJoinRoomsOnce(daysAllowed) {
        if (roomsBound) return;
        const coordId = getCoordId();
        const s = window.__reqSocket;
        if (!coordId || !s) return;
        // Unirse a drops
        window.__reqJoinDrops?.({ coord_id: coordId });
        // Unirse a todas las rooms de citas por día permitido
        (daysAllowed || []).forEach(day => {
            window.__reqJoinApDay?.({ coord_id: coordId, day });
        });
        // Handlers (evitar duplicados)
        s.off?.("appointment_created");
        s.off?.("drop_created");
        s.off?.("request_status_changed");
        const scheduleReload = debounce(() => loadDashboard(), 250);
        s.on("appointment_created", (p) => { scheduleReload(); });
        s.on("drop_created", (p) => { scheduleReload(); });
        s.on("request_status_changed", (p) => { scheduleReload(); });
        roomsBound = true;
    }

    function debounce(fn, wait) {
        let t = null; return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), wait); };
    }

    // Carga inicial
    await loadDashboard();
})();
