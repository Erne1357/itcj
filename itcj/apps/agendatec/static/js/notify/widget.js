// static/js/notify/widget.js
(() => {
    const $ = (s) => document.querySelector(s);
    const badge = $("#notifBadge");
    const panel = $("#notifPanel");
    const list = $("#notifList");
    const btn = $("#notifFab");
    const tabRecent = $("#notifTabRecent");
    const tabHistory = $("#notifTabHistory");
    const btnMarkAll = $("#notifMarkAll");

    let unreadCount = 0;
    let historyCursor = null; // before_id para paginar
    let outsideHandlersBound = false;

    function bindOutsideHandlers() {
        if (outsideHandlersBound) return;
        // pequeño delay para no cerrar por el mismo click que lo abre
        setTimeout(() => {
            document.addEventListener("pointerdown", onGlobalPointerDown, true);
            document.addEventListener("keydown", onGlobalKeyDown, true);
            outsideHandlersBound = true;
        }, 0);
    }
    function unbindOutsideHandlers() {
        if (!outsideHandlersBound) return;
        document.removeEventListener("pointerdown", onGlobalPointerDown, true);
        document.removeEventListener("keydown", onGlobalKeyDown, true);
        outsideHandlersBound = false;
    }
    function onGlobalPointerDown(e) {
        // si el click fue dentro del panel o sobre el botón, no cerrar
        const t = e.target;
        if (panel?.contains(t)) return;
        if (btn?.contains(t)) return;
        closePanel();
    }
    function onGlobalKeyDown(e) {
        if (e.key === "Escape") closePanel();
    }
    function openPanel() {
        if (!panel) return;
        panel.hidden = false;
        panel.setAttribute("data-open", "1");
        bindOutsideHandlers();
    }
    function closePanel() {
        if (!panel) return;
        panel.hidden = true;
        panel.removeAttribute("data-open");
        unbindOutsideHandlers();
    }
    function togglePanel() {
        if (panel?.hidden) openPanel(); else closePanel();
    }
    function setBadge(n) {
        unreadCount = Math.max(0, Number(n || 0));
        if (unreadCount > 0) {
            badge.textContent = String(unreadCount);
            badge.hidden = false;
        } else {
            badge.hidden = true;
        }
    }

    async function fetchUnreadCount() {
        // trae pocas y cuenta
        const r = await fetch("/api/agendatec/v1/notifications?unread=1&limit=50", { credentials: "include" });
        const data = await r.json();
        setBadge((data.items || []).length);
    }

    function itemHTML(n) {
        const when = n.created_at ? new Date(n.created_at).toLocaleString("es-MX", { hour: "2-digit", minute: "2-digit", month: "2-digit", day: "2-digit" }) : "";
        const body = n.body ? `<div class="small text-muted">${escapeHtml(n.body).replace(/\n/g, "<br>")}</div>` : "";
        return `<div class="notif-item ${n.is_read ? "" : "unread"}" data-id="${n.id}">
      <div class="fw-semibold">${escapeHtml(n.title || "")}</div>
      ${body}
      <div class="small text-muted">${when}</div>
    </div>`;
    }

    async function loadRecent() {
        const r = await fetch("/api/agendatec/v1/notifications?limit=8", { credentials: "include" });
        const data = await r.json();
        list.innerHTML = (data.items || []).map(itemHTML).join("") || `<div class="text-muted px-2 py-1">Sin notificaciones.</div>`;
    }

    async function loadHistory(reset = false) {
        let url = "/api/agendatec/v1/notifications?limit=20";
        if (!reset && historyCursor) url += `&before_id=${historyCursor}`;
        const r = await fetch(url, { credentials: "include" });
        const data = await r.json();
        const items = data.items || [];
        if (reset) list.innerHTML = "";
        list.insertAdjacentHTML("beforeend", items.map(itemHTML).join("") || `<div class="text-muted px-2 py-1">Sin notificaciones.</div>`);
        if (items.length) {
            historyCursor = items[items.length - 1].id;
        }
    }

    function openPanel() {
        panel.classList.add("open");
        // por defecto: recientes
        tabRecent.classList.add("active");
        tabHistory.classList.remove("active");
        list.innerHTML = "";
        loadRecent();
    }
    function closePanel() {
        panel.classList.remove("open");
    }

    btn?.addEventListener("click", () => {
        if (panel.classList.contains("open")) closePanel(); else openPanel();
    });

    tabRecent?.addEventListener("click", () => {
        tabRecent.classList.add("active");
        tabHistory.classList.remove("active");
        list.innerHTML = "";
        loadRecent();
    });

    tabHistory?.addEventListener("click", () => {
        tabHistory.classList.add("active");
        tabRecent.classList.remove("active");
        list.innerHTML = "";
        historyCursor = null;
        loadHistory(true);
    });

    btnMarkAll?.addEventListener("click", async () => {
        await fetch("/api/agendatec/v1/notifications/read-all", { method: "PATCH", credentials: "include" });
        setBadge(0);
        // marca visualmente
        list.querySelectorAll(".notif-item.unread").forEach(el => el.classList.remove("unread"));
    });

    document.addEventListener("notif:push", (e) => {
        const n = e.detail;
        // Prepend en la lista si está abierta en “Recientes”
        if (panel.classList.contains("open") && tabRecent.classList.contains("active")) {
            list.insertAdjacentHTML("afterbegin", itemHTML(n));
        }
        setBadge(unreadCount + 1);
        // mini feedback
        try { showToast?.(n.title || "Nueva notificación", "info"); } catch { }
    });

    function escapeHtml(str) { return (str || "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;"); }

    // init
    fetchUnreadCount().catch(() => { });
})();
