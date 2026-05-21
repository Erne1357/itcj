/* =============================================================================
   AgendaTec — Socket connection status indicator
   -----------------------------------------------------------------------------
   Muestra un dot (verde/ámbar/rojo) al lado de un anchor element para indicar
   estado del Socket.IO. Se acopla a un socket pasado por parámetro o detecta
   window.__reqSocket automáticamente.
   Expone window.AgendaTec.SocketStatus.
   ============================================================================= */
(function () {
  "use strict";

  const LABELS = {
    connected:    "Conectado",
    reconnecting: "Reconectando…",
    disconnected: "Sin conexión",
  };

  /**
   * Monta el indicador como hijo del anchor.
   * @param {object} cfg
   *   - anchor   {HTMLElement|string} contenedor donde se inserta el dot
   *   - socket   {Object?} socket.io client (opcional; intenta window.__reqSocket)
   *   - label    {boolean} mostrar texto al lado del dot (default true)
   * @returns {{ destroy: Function, setState: Function }}
   */
  function mount(cfg) {
    const anchor = typeof cfg.anchor === "string"
      ? document.querySelector(cfg.anchor)
      : cfg.anchor;
    if (!anchor) return { destroy: () => {}, setState: () => {} };

    const showLabel = cfg.label !== false;
    const span = document.createElement("span");
    span.className = "at-status-dot at-status-dot--disconnected ms-2";
    if (showLabel) {
      const txt = document.createElement("span");
      txt.className = "at-status-dot__text";
      txt.textContent = LABELS.disconnected;
      span.appendChild(txt);
    }
    span.setAttribute("role", "status");
    span.setAttribute("aria-live", "polite");
    anchor.appendChild(span);

    function setState(state) {
      span.classList.remove(
        "at-status-dot--connected",
        "at-status-dot--reconnecting",
        "at-status-dot--disconnected",
      );
      span.classList.add(`at-status-dot--${state}`);
      if (showLabel) {
        const txt = span.querySelector(".at-status-dot__text");
        if (txt) txt.textContent = LABELS[state] || "";
      }
    }

    function bind(socket) {
      if (!socket) return;
      if (socket.connected) setState("connected");
      socket.on("connect",            () => setState("connected"));
      socket.on("disconnect",         () => setState("disconnected"));
      socket.on("reconnect_attempt",  () => setState("reconnecting"));
      socket.on("reconnect_failed",   () => setState("disconnected"));
      socket.on("reconnect",          () => setState("connected"));
    }

    if (cfg.socket) {
      bind(cfg.socket);
    } else {
      /* Espera lazy a window.__reqSocket (algunos clientes lo asignan después). */
      let tries = 0;
      const poll = setInterval(() => {
        tries += 1;
        if (window.__reqSocket) {
          clearInterval(poll);
          bind(window.__reqSocket);
        } else if (tries > 40) { /* 40 * 250ms = 10s */
          clearInterval(poll);
        }
      }, 250);
    }

    return {
      destroy: () => span.remove(),
      setState,
    };
  }

  window.AgendaTec = window.AgendaTec || {};
  window.AgendaTec.SocketStatus = { mount };
})();
