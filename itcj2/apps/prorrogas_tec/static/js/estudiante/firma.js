// Lienzo de firma a mano, compartido por la solicitud y Mi prórroga.
(function () {
  function crear(canvas, onChange) {
    const ctx = canvas.getContext("2d");
    let trazos = 0, dibujando = false;
    const avisar = () => { if (onChange) onChange(); };

    // El fondo queda transparente: el servidor rechaza una firma sin trazos o sin alfa.
    function ajustar() {
      const r = window.devicePixelRatio || 1, w = canvas.clientWidth, h = canvas.clientHeight;
      canvas.width = Math.round(w * r);
      canvas.height = Math.round(h * r);
      ctx.setTransform(r, 0, 0, r, 0, 0);
      ctx.lineWidth = 2.2;
      ctx.lineCap = ctx.lineJoin = "round";
      ctx.strokeStyle = "#1A130E";
    }

    function punto(e) {
      const b = canvas.getBoundingClientRect();
      return [e.clientX - b.left, e.clientY - b.top];
    }

    canvas.addEventListener("pointerdown", function (e) {
      dibujando = true;
      canvas.setPointerCapture(e.pointerId);
      const [x, y] = punto(e);
      ctx.beginPath();
      ctx.moveTo(x, y);
      ctx.lineTo(x + .01, y);
      ctx.stroke();
      e.preventDefault();
    });
    canvas.addEventListener("pointermove", function (e) {
      if (!dibujando) return;
      const [x, y] = punto(e);
      ctx.lineTo(x, y);
      ctx.stroke();
    });
    function fin() {
      if (!dibujando) return;
      dibujando = false;
      trazos++;
      avisar();
    }
    canvas.addEventListener("pointerup", fin);
    canvas.addEventListener("pointercancel", fin);

    // Girar el teléfono cambia el ancho; con trazos no se toca para no borrar la firma.
    window.addEventListener("resize", function () { if (!trazos) ajustar(); });

    ajustar();
    return {
      vacia: () => trazos === 0,
      limpiar: function () {
        ctx.save();
        ctx.setTransform(1, 0, 0, 1, 0, 0);
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        ctx.restore();
        trazos = 0;
        avisar();
      },
      dataURL: () => canvas.toDataURL("image/png"),
    };
  }
  window.Firma = { crear: crear };
})();
