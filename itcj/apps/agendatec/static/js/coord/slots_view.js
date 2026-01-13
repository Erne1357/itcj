// static/js/coord/slots_view.js
// Vista visual del día en /coord/slots (KPIs + tira + tabla) con refresh en vivo.

(() => {
    function joinDayRoomsWhenSocketReady(day) {
        function tryJoin() {
            const s = slotsSock();
            if (s && s.connected) {
                joinDayRooms(day);
            } else {
                setTimeout(tryJoin, 400); // espera 400ms y reintenta
            }
        }
        tryJoin();
    }
    const $ = (sel) => document.querySelector(sel);
    const fmtName = (stu) => {
        if (!stu) return "—";
        const n = stu.full_name || "—";
        const c = stu.control_number || stu.username || "";
        return c ? `${n} (${c})` : n;
    };

    // Elementos
    const daySel = $("#cfgDay");        // selector del “Configurar horario”
    const dayDel = $("#cfgDayDel");     // selector del bloque “Eliminar horas”
    const kpiTotal = $("#kpiTotal");
    const kpiFree = $("#kpiFree");
    const kpiBooked = $("#kpiBooked");
    const kpiWins = $("#kpiWindows");
    const strip = $("#dayStrip");
    const tbody = $("#dayTableBody");

    if (!daySel || !strip || !tbody) return;

    // Helpers sockets
    const slotsSock = () => window.__slotsSocket;

    // Unir a la room del día actual
    function joinDayRooms(day) {
        if (typeof window.__joinDay === "function") {
            window.__joinDay(day);
        }
    }

    // Cargar y renderizar
    async function loadAndRender(day) {
        // KPIs de ventanas
        await loadWindowsKpi(day);
        document.getElementById("tittleView").innerHTML = "Vista del día seleccionado " + day;
        // Slots con/cita
        const slots = await loadSlotsWithAppointments(day);
        render(slots);
    }

    async function loadWindowsKpi(day) {
        try {
            const url = new URL("/api/agendatec/v1/coord/day-config", window.location.origin);
            url.searchParams.set("day", day);
            const r = await fetch(url, { credentials: "include" });
            if (!r.ok) throw 0;
            const data = await r.json();
            kpiWins.textContent = (data.items || []).length;
        } catch {
            kpiWins.textContent = "—";
        }
    }

    async function loadSlotsWithAppointments(day) {
        try {
            const url = new URL("/api/agendatec/v1/coord/appointments", window.location.origin);
            url.searchParams.set("day", day);
            url.searchParams.set("include_empty", "1");
            const r = await fetch(url, { credentials: "include" });
            if (!r.ok) throw 0;
            const data = await r.json();
            return data.slots || [];
        } catch {
            return [];
        }
    }

    function render(slots) {
        const total = slots.length;
        const booked = slots.filter(s => !!s.appointment).length;
        const free = total - booked;

        kpiTotal.textContent = total;
        kpiBooked.textContent = booked;
        kpiFree.textContent = free;

        // Tira
        strip.innerHTML = "";
        if (!total) {
            strip.innerHTML = `<div class="text-muted">No hay slots configurados para este día.</div>`;
        } else {
            for (const s of slots) {
                const booked = !!s.appointment;
                const chip = document.createElement("div");
                chip.className = `slot-chip ${booked ? "slot-booked" : "slot-free"}`;
                const who = booked ? (s.appointment.student?.full_name || "Reservado") : "Libre";
                chip.title = `${s.start}–${s.end} · ${who}`;
                chip.innerHTML = `<span class="tt">${s.start}–${s.end}</span>`;
                strip.appendChild(chip);
            }
        }

        // Tabla
        tbody.innerHTML = "";
        for (const s of slots) {
            const ap = s.appointment;
            const tr = document.createElement("tr");
            const who = ap ? fmtName(ap.student) : "—";
            const prog = ap ? (ap.program?.name || "—") : "—";
            const stBadge = ap
                ? `<span class="badge text-bg-primary">Reservado</span>`
                : `<span class="badge text-bg-secondary">Libre</span>`;
            tr.innerHTML = `
        <td>${s.start}–${s.end}</td>
        <td>${stBadge}</td>
        <td>${who}</td>
        <td>${prog}</td>
      `;
            tbody.appendChild(tr);
        }
    }

    // Cambios de día: reutilizamos el selector de “Configurar horario”
    function currentDay() { return daySel.value; }
    function onDayChange() {
        const d = currentDay();
        if (!d) return;
        joinDayRoomsWhenSocketReady(d);
        loadAndRender(d);
        if (dayDel) dayDel.value = d;
    }


    // Bind change
    daySel.addEventListener("change", onDayChange);

    // Esperar a que slots_init.js termine de cargar los días
    document.addEventListener('slotsInitReady', (e) => {
        const d = e.detail?.selectedDay;
        if (d) {
            joinDayRoomsWhenSocketReady(d);
            loadAndRender(d);
            if (dayDel) dayDel.value = d;
        }
    });

    // Sockets: refrescar vista al vuelo
    (function wireSocketRefresh() {
        const s = slotsSock();
        if (!s) {
            // si el cliente /slots aún no está listo, reintenta
            setTimeout(wireSocketRefresh, 500);
            return;
        }
        s.off?.("slots_window_changed");
        s.off?.("slot_booked");
        s.off?.("slot_released");

        const refreshIfDay = (payloadDay) => {
            const d = currentDay();
            if (!d || payloadDay !== d) return;
            loadAndRender(d);
        };

        s.on("slots_window_changed", (p) => refreshIfDay(p?.day));
        s.on("slot_booked", (p) => refreshIfDay(p?.day));
        s.on("slot_released", (p) => refreshIfDay(p?.day));
    })();

    // NOTA: La carga inicial ahora se hace desde el evento 'slotsInitReady'
    // disparado por slots_init.js cuando los días están listos
})();
