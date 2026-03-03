// static/js/sockets/notify_client.js
(() => {
  const ensureIo = () =>
    new Promise((resolve, reject) => {
      if (window.io) return resolve();
      const s = document.createElement("script");
      s.src = "https://cdn.socket.io/4.7.5/socket.io.min.js";
      s.crossOrigin = "anonymous";
      s.onload = () => resolve();
      s.onerror = reject;
      document.head.appendChild(s);
    });

  ensureIo().then(() => {
    if (window.__notifySocket) return;
    const socket = io("/notify", {
      withCredentials: true,
      reconnection: true,
      timeout: 20000,
      transport: ["websocket"],
      upgrade: true
    });
    window.__notifySocket = socket;

    socket.on("notify", (n) => {
      // n es {id,type,title,body,is_read,created_at,data}
      document.dispatchEvent(new CustomEvent("notif:push", { detail: n }));
    });
  }).catch(err => console.error("[WS notify] no se pudo cargar socket.io", err));
})();
