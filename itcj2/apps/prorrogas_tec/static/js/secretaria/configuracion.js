// Prórrogas · Configuración (vista de secretaría): periodo de Prórrogas de cada semestre.
// Las reglas se repiten aquí para avisar mientras se captura; quien decide es el servidor.
// API: /api/prorrogas/v2/configuracion/periodos. Todo texto del servidor entra con textContent.
(function () {
  "use strict";

  const root = document.querySelector(".cfg");
  if (!root) return;
  const API = root.dataset.api;
  const $ = (id) => document.getElementById(id);
  const MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];
  const KEYS = ["abre", "cierra", "pago1", "pago2"];
  const CHIP = { sin: "Sin configurar", por: "Por abrir", abi: "Abierto", cer: "Cerrado" };
  const HITOS = [["abre", "Abre solicitudes", "is-sol"], ["cierra", "Cierra solicitudes", "is-sol"],
    ["pago1", "Pago 1", "is-pago"], ["pago2", "Pago 2", "is-pago"], ["fin", "Fin de semestre", "is-fin"]];

  const st = { hoy: "", items: [], sem: null, draft: {}, puede: false };
  const actual = () => st.items.find((x) => x.id === st.sem);

  function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  // Las fechas ISO se leen por partes: new Date("2026-03-01") sería UTC y mostraría el día anterior.
  const partes = (iso) => iso.split("-").map(Number);
  const f = (iso) => { const [y, m, d] = partes(iso); return `${d} ${MESES[m - 1]} ${y}`; };
  const t = (iso) => { const [y, m, d] = partes(iso); return Date.UTC(y, m - 1, d); };
  const dias = (a, b) => Math.round((t(b) - t(a)) / 864e5);
  const plural = (n) => `${n} ${n === 1 ? "día" : "días"}`;

  function mensaje(msg) { const m = $("cfgMsg"); m.textContent = msg || ""; m.hidden = !msg; }

  function toast(msg) {
    const n = $("secToast");
    n.textContent = msg;
    n.hidden = false;
    clearTimeout(toast.t);
    toast.t = setTimeout(() => { n.hidden = true; }, 2600);
  }

  async function api(path, body) {
    const o = { credentials: "include" };
    if (body) Object.assign(o, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    try {
      const r = await fetch(API + path, o);
      return { ok: r.ok, data: await r.json().catch(() => ({})) };
    } catch (e) {
      return { ok: false, data: { message: "Sin conexión con el servidor." } };
    }
  }

  function errores(dr, S) {
    const e = {};
    const otros = st.items.filter((x) => x.id !== S.id && x.periodo).map((x) => ({ label: x.label, ...x.periodo }));
    const dentro = (d, p) => d >= p.abre && d <= p.cierra;
    const encima = (o) => `Se encima con ${o.label} (${f(o.abre)} – ${f(o.cierra)}).`;
    if (dr.abre) { const o = otros.find((p) => dentro(dr.abre, p)); if (o) e.abre = encima(o); }
    if (dr.abre && dr.cierra && dr.cierra <= dr.abre) e.cierra = `Debe ser después de la apertura (${f(dr.abre)}).`;
    else if (dr.cierra) {
      const o = otros.find((p) => dentro(dr.cierra, p) || (dr.abre && dr.abre < p.abre && dr.cierra > p.cierra));
      if (o) e.cierra = encima(o);
    }
    if (dr.pago1 && dr.abre && dr.pago1 <= dr.abre) e.pago1 = `Debe ser después de la apertura (${f(dr.abre)}).`;
    else if (dr.pago1 && dr.pago1 >= S.fin) e.pago1 = `Debe ser antes del fin del semestre (${f(S.fin)}).`;
    if (dr.pago1 && dr.pago2 && dr.pago2 <= dr.pago1) e.pago2 = `Debe ser después del pago 1 (${f(dr.pago1)}).`;
    else if (dr.pago2 && dr.pago2 >= S.fin) e.pago2 = `Debe ser antes del fin del semestre (${f(S.fin)}).`;
    return e;
  }

  function aviso(estado, sv) {
    if (estado === "sin") return "Los alumnos no pueden solicitar hasta que guardes las fechas.";
    if (estado === "cer") return "Los alumnos ya no pueden solicitar prórroga este semestre.";
    if (estado === "por") return `Las solicitudes abren el ${f(sv.abre)}, en ${plural(dias(st.hoy, sv.abre))}.`;
    const n = dias(st.hoy, sv.cierra);
    return `Los alumnos pueden solicitar hasta el ${f(sv.cierra)} · ${n ? `quedan ${plural(n)}` : "hoy es el último día"}.`;
  }

  function pie(nErr, sucio, completo, sv) {
    if (nErr) return ["is-err", `${nErr} ${nErr === 1 ? "fecha por corregir" : "fechas por corregir"}`];
    if (sucio && !completo) return ["", "Faltan fechas por capturar"];
    if (sucio) return ["is-sucio", "Cambios sin guardar"];
    return sv ? ["is-ok", "Todo guardado"] : ["", "Captura las cuatro fechas"];
  }

  function pintarCampos(dr, er) {
    root.querySelectorAll(".cfg-field").forEach((c) => {
      const k = c.dataset.k, inp = c.querySelector("input"), txt = c.querySelector(".cfg-date-txt"), err = c.querySelector(".cfg-err");
      if (inp.value !== dr[k]) inp.value = dr[k];
      txt.textContent = dr[k] ? f(dr[k]) : "Elige una fecha";
      txt.classList.toggle("is-vacio", !dr[k]);
      c.classList.toggle("has-err", !!er[k]);
      inp.setAttribute("aria-invalid", er[k] ? "true" : "false");
      err.hidden = !er[k];
      err.lastElementChild.textContent = er[k] || "";
    });
  }

  function pintarLinea(S, dr, er) {
    const vals = { ...dr, fin: S.fin };
    const todos = [S.inicio, S.fin, ...KEYS.map((k) => dr[k]).filter(Boolean)].map(t);
    const t0 = Math.min(...todos), t1 = Math.max(...todos);
    const n = (x) => 3 + 94 * (t(x) - t0) / Math.max(1, t1 - t0);
    const barra = (cls, izq, ancho) => { const b = el("div", cls); b.style.left = izq + "%"; b.style.width = ancho + "%"; return b; };
    const fechados = HITOS.filter(([k]) => vals[k]).sort((a, b) =>
      (vals[a[0]] < vals[b[0]] ? -1 : vals[a[0]] > vals[b[0]] ? 1 : HITOS.indexOf(a) - HITOS.indexOf(b)));
    const orden = [...fechados, ...HITOS.filter(([k]) => !vals[k])];
    const claseN = (k, cls) => (er[k] ? "is-err" : vals[k] ? cls : "is-vacio");

    const piezas = [el("div", "cfg-rail"), barra("cfg-tl-sem", n(S.inicio), n(S.fin) - n(S.inicio))];
    if (dr.abre && dr.cierra && dr.cierra > dr.abre) piezas.push(barra("cfg-tl-win", n(dr.abre), n(dr.cierra) - n(dr.abre)));
    const hayHoy = t(st.hoy) >= t0 && t(st.hoy) <= t1;
    if (hayHoy) {
      const h = el("div", "cfg-tl-hoy");
      h.style.left = n(st.hoy) + "%";
      h.append(el("span", null, "Hoy"), el("i"));
      piezas.push(h);
    }
    fechados.forEach(([k, , cls], i) => {
      const p = el("span", `cfg-n ${claseN(k, cls)}`, i + 1);
      p.style.left = n(vals[k]) + "%";
      piezas.push(p);
    });
    $("cfgLinea").replaceChildren(...piezas);

    const ley = $("cfgLeyHoy");
    ley.hidden = !hayHoy;
    ley.lastElementChild.textContent = `Hoy, ${f(st.hoy)}`;

    $("cfgPasos").replaceChildren(...orden.map(([k, label, cls], i) => {
      let gap = "";
      if (vals[k] && i === 0) {
        const d = dias(vals[k], S.inicio);
        gap = d > 0 ? `${plural(d)} antes del inicio del semestre` : d < 0 ? `${plural(-d)} después del inicio del semestre` : "Mismo día que inicia el semestre";
      } else if (vals[k]) {
        const d = dias(vals[orden[i - 1][0]], vals[k]);
        gap = d > 0 ? `+${plural(d)}` : "Mismo día";
      } else gap = "Pendiente de capturar";
      const li = el("li");
      const izq = el("div", "cfg-paso-izq");
      izq.append(el("span", `cfg-n ${claseN(k, cls)}`, i + 1), el("i"));
      const der = el("div", "cfg-paso" + (er[k] ? " is-err" : ""));
      const top = el("div", "cfg-paso-top");
      top.append(el("span", null, label), el("span", "cfg-paso-fecha" + (vals[k] ? "" : " is-vacio"), vals[k] ? f(vals[k]) : "Sin fecha"));
      der.append(top, el("div", "cfg-paso-gap", gap));
      li.append(izq, der);
      return li;
    }));
  }

  function render() {
    const S = actual(), dr = st.draft, sv = S.periodo, er = errores(dr, S), nErr = Object.keys(er).length;
    const completo = KEYS.every((k) => dr[k]);
    const sucio = sv ? KEYS.some((k) => dr[k] !== sv[k]) : KEYS.some((k) => dr[k]);
    st.puede = sucio && completo && !nErr;

    $("cfgIni").textContent = f(S.inicio);
    $("cfgFin").textContent = f(S.fin);
    const estado = !sv ? "sin" : st.hoy < sv.abre ? "por" : st.hoy <= sv.cierra ? "abi" : "cer";
    $("cfgBanner").dataset.estado = estado;
    $("cfgChip").textContent = CHIP[estado];
    $("cfgAviso").textContent = aviso(estado, sv);

    pintarCampos(dr, er);
    pintarLinea(S, dr, er);

    const [cls, txt] = pie(nErr, sucio, completo, sv);
    const status = $("cfgStatus");
    status.className = "cfg-status " + cls;
    status.lastElementChild.textContent = txt;
    $("cfgDescartar").hidden = !(sucio && sv);
    $("cfgGuardar").setAttribute("aria-disabled", String(!st.puede));
  }

  function elegir(id) {
    st.sem = id;
    st.draft = { abre: "", cierra: "", pago1: "", pago2: "", ...actual().periodo };
    mensaje("");
    render();
  }

  function datos(d) { st.hoy = d.hoy; st.items = d.items || []; }

  async function cargar() {
    const r = await api("");
    if (!r.ok) { mensaje(r.data.message || "No se pudieron cargar los semestres."); return; }
    datos(r.data);
    if (!st.items.length) { $("cfgVacio").hidden = false; return; }
    const sel = $("cfgSem");
    st.items.forEach((p) => { const o = el("option", null, p.label); o.value = p.id; sel.append(o); });
    $("cfgMain").hidden = false;
    elegir(st.items[0].id);
  }

  root.querySelectorAll(".cfg-field input").forEach((inp) => {
    const k = inp.closest(".cfg-field").dataset.k;
    inp.addEventListener("input", () => { st.draft[k] = inp.value; mensaje(""); render(); });
    inp.addEventListener("click", () => { try { inp.showPicker(); } catch (e) { /* sin selector: se escribe a mano */ } });
  });

  $("cfgSem").addEventListener("change", (e) => elegir(Number(e.target.value)));
  $("cfgDescartar").addEventListener("click", () => elegir(st.sem));

  $("cfgForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const b = $("cfgGuardar");
    if (!st.puede || b.dataset.ocupado) return;
    b.dataset.ocupado = "1";
    const r = await api(`/${st.sem}`, st.draft);
    delete b.dataset.ocupado;
    if (!r.ok) { mensaje(r.data.message || "No se pudo guardar el periodo."); return; }
    datos(r.data);
    elegir(st.sem);
    toast("Periodo guardado");
  });

  cargar();
})();
