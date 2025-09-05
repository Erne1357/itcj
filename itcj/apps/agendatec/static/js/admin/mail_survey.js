// static/js/admin/mail_survey.js
(() => {
  const $ = (s) => document.querySelector(s);
  const log = (msg) => {
    const el = $("#surveyLog");
    if (el) {
      const p = document.createElement("div");
      p.textContent = msg;
      el.prepend(p);
    } else {
      console.log(msg);
    }
  };

  const endpoint = "/api/agendatec/v1/admin/surveys/send";

  function currentRangeQS() {
    const q = new URLSearchParams();
    const f = $("#fltFrom")?.value;
    const t = $("#fltTo")?.value;
    if (f) q.set("from", f);
    if (t) q.set("to", t);
    return q.toString();
  }

  async function sendBatch({ test, limit = 700, offset = 0 } = {}) {
    const qs = currentRangeQS();
    const url = `${endpoint}?${qs}&limit=${limit}&offset=${offset}&test=${test ? "1" : "0"}`;
    const r = await fetch(url, { method: "POST", credentials: "include" });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return r.json();
  }

  async function runBatches({ test }) {
    let offset = 0;
    const limit = 200;

    // Confirmaciones
    if (test) {
      if (!confirm("¿Enviar lote de PRUEBA? Todo irá al destinatario de prueba.")) return;
    } else {
      if (!confirm("¿Enviar lote en PRODUCCIÓN a alumnos?")) return;
    }

    // Enviar UN solo lote por clic (rápido). Si quieres en bucle, descomenta el while.
    try {
      const res = await sendBatch({ test, limit, offset });
      const mode = res.test_mode ? "PRUEBA" : "PRODUCCIÓN";
      log(`[${mode}] Enviados: ${res.sent}, omitidos: ${res.skipped}, errores: ${res.errors?.length || 0}, candidatos totales: ${res.total_candidates}, siguiente offset: ${res.next_offset}`);
      if (res.errors && res.errors.length) {
        console.warn("Errores de envío:", res.errors);
      }
      // Sugerir siguiente lote si aplica
      if (res.next_offset < res.total_candidates) {
        const btn = document.createElement("button");
        btn.className = "btn btn-sm btn-outline-secondary mt-2";
        btn.textContent = "Enviar siguiente lote";
        btn.onclick = () => runBatches({ test });
        $("#surveyLog")?.prepend(btn);
      } else {
        log("No hay más candidatos en el rango.");
      }
    } catch (e) {
      log("Falló el envío: " + (e?.message || e));
      console.error(e);
      alert("Error al enviar: revisa la consola/servidor.");
    }
  }

  $("#btnSurveyTest")?.addEventListener("click", () => runBatches({ test: true  }));
  $("#btnSurveyLive")?.addEventListener("click", () => runBatches({ test: false }));
})();
