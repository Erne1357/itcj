/**
 * shared/pager.js — la tira de NÚMEROS de página y el estado de la lista en la
 * URL. Compartido por las dos listas paginadas EN EL SERVIDOR de la app:
 * `documents/document-list.js` (documentos y panel de documentos) y
 * `work/work-items.js` (incidencias y eventos de programa).
 *
 * Expone SOLO `window.AdhocPager` (IIFE, sin globales sueltas).
 *
 * POR QUÉ EXISTE
 * --------------
 * Las dos listas pintaban únicamente "anterior / siguiente". Con las 276
 * incidencias reales del SGC a 25 por página son 12 páginas: llegar a la última
 * eran ONCE clics, y cada uno una consulta. Y ni la página ni los filtros
 * viajaban en la URL, así que una vista filtrada no se podía compartir por
 * correo ni sobrevivía a un F5.
 *
 * El defecto era el mismo en los dos módulos y la solución también, así que
 * vive aquí una sola vez. Va en `shared/` y se carga desde el <head> de
 * `base_adhoc.html`, junto a `shared/table-filter.js` y por su misma razón: si
 * cada pantalla tuviera que acordarse de incluirlo, el fallo sería SILENCIOSO
 * —la lista seguiría paginando de una en una y nadie lo notaría—.
 *
 * ES UNA BIBLIOTECA, NO UN MÓDULO DE PANTALLA: no se registra en
 * `AdhocUtils.onReady`, no instala ni un listener y no guarda estado. Por eso
 * no tiene nada que ver con el ciclo de montaje/desmontaje de HTMX y no puede
 * romperlo. Los clics los recoge la MISMA delegación que cada módulo ya tiene
 * sobre su raíz, mirando el atributo `data-adhoc-goto-page` de estos botones.
 *
 * MARCADO QUE PRODUCE (todo con createElement + textContent: cero innerHTML)
 * -------------------------------------------------------------------------
 *   <div class="adhoc-pager-pages" data-adhoc-pager-pages role="group" aria-label="Páginas">
 *     <button class="adhoc-pager-page" data-adhoc-goto-page="1" aria-label="Ir a la página 1">1</button>
 *     <span class="adhoc-pager-gap" aria-hidden="true">…</span>
 *     <button class="adhoc-pager-page" data-adhoc-goto-page="5" aria-current="page" …>5</button>
 *     …
 *   </div>
 *
 * Las clases las viste la hoja de cada pantalla (`documents/documents.css`,
 * `work/work-items.css`), que es donde ya vivían las del paginador viejo.
 */
(function () {
    'use strict';

    //: Cuántas páginas se enseñan a cada lado de la actual.
    //:
    //: DOS, y no una ni tres. Con las 12 páginas de incidencias cualquiera de
    //: ellas queda a DOS clics desde cualquier otra tanto con radio 1 como con
    //: radio 2 —la primera y la última salen siempre—, así que el número no lo
    //: decide el peor caso sino el caso COMÚN: repasar la lista hacia delante.
    //: Con radio 1 avanzar dos páginas son dos clics y dos consultas; con radio
    //: 2 es uno. Radio 3 no quita ni un clic y añade dos botones que en un
    //: teléfono de 360 px ya obligan a partir la tira en dos filas.
    //:
    //: Y hay un efecto de estabilidad que se agradece con el ratón: a partir de
    //: 10 páginas la tira mide SIEMPRE nueve huecos, así que los números no se
    //: mueven de sitio al paginar y el siguiente clic cae donde uno está
    //: mirando.
    var RADIO = 2;

    //: Nombre del parámetro de página en la URL del navegador. Es el mismo que
    //: usa la API a propósito: una sola palabra para el mismo concepto.
    var PARAM_PAGINA = 'page';

    var ATTR_TIRA = 'data-adhoc-pager-pages';
    var ATTR_IR = 'data-adhoc-goto-page';

    // ==================== LA VENTANA DE PÁGINAS ====================

    /**
     * Qué números se enseñan: primera, última, una ventana alrededor de la
     * actual, y elisiones donde falten páginas.
     *
     * El umbral para no elidir nada es `2*radio + 5`, que es exactamente el
     * número de huecos del caso peor (primera · … · radio · actual · radio · …
     * · última). Por debajo de él una elisión escondería MENOS páginas de las
     * que ocupa, que es cómo salen esos paginadores con un "…" tapando un solo
     * número.
     *
     * @param {number} pagina página actual (1-based)
     * @param {number} totalPaginas total de páginas
     * @param {number} [radio] páginas a cada lado; por defecto RADIO
     * @returns {Array<number|null>} números, con `null` por cada elisión
     */
    function ventana(pagina, totalPaginas, radio) {
        var r = (typeof radio === 'number' && radio >= 1) ? radio : RADIO;
        var total = Math.max(1, totalPaginas | 0);
        var p = Math.min(Math.max(1, pagina | 0), total);
        var out = [];
        var i;

        if (total <= 2 * r + 5) {
            for (i = 1; i <= total; i++) out.push(i);
            return out;
        }

        // Pegado al principio: la ventana no cabe hacia la izquierda, así que
        // se gasta entera hacia la derecha en vez de dejar un hueco muerto.
        if (p <= r + 3) {
            for (i = 1; i <= 2 * r + 3; i++) out.push(i);
            out.push(null);
            out.push(total);
            return out;
        }

        // Pegado al final: lo simétrico.
        if (p >= total - r - 2) {
            out.push(1);
            out.push(null);
            for (i = total - 2 * r - 2; i <= total; i++) out.push(i);
            return out;
        }

        out.push(1);
        out.push(null);
        for (i = p - r; i <= p + r; i++) out.push(i);
        out.push(null);
        out.push(total);
        return out;
    }

    // ==================== PINTADO ====================

    function botonPagina(numero, actual) {
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'adhoc-pager-page';
        btn.textContent = String(numero);
        btn.setAttribute(ATTR_IR, String(numero));
        btn.setAttribute('aria-label', 'Ir a la página ' + numero);

        if (numero === actual) {
            // `aria-current` es LO QUE dice "estás aquí"; la clase solo lo
            // pinta. Por eso el CSS cuelga del atributo y no de una clase
            // paralela: así es imposible que haya un botón resaltado que el
            // lector de pantalla no anuncie, que es como se rompen estos
            // paginadores.
            //
            // Y va HABILITADO. Deshabilitarlo lo saca del recorrido del
            // tabulador, así que quien navega con teclado pierde la referencia
            // de dónde está justo en el control que se la da. Que pulsarlo no
            // haga nada lo resuelve quien escucha el clic, comparando con su
            // página actual.
            btn.setAttribute('aria-current', 'page');
        }
        return btn;
    }

    function elision() {
        var span = document.createElement('span');
        span.className = 'adhoc-pager-gap';
        span.textContent = '…';
        // El salto ya lo cuentan los números de los lados; anunciar "puntos
        // suspensivos" entre cada par solo alarga la lectura.
        span.setAttribute('aria-hidden', 'true');
        return span;
    }

    /**
     * Pinta (o repinta) la tira de números dentro del paginador de la pantalla.
     *
     * La tira se REUTILIZA si ya está en el contenedor. Importa para el botón
     * ATRÁS: el caché del historial de HTMX guarda el `innerHTML` del `<body>`,
     * así que al restaurar la tira vuelve puesta; creando otra habría dos.
     *
     * @param {HTMLElement} contenedor el paginador que ya existe en la plantilla
     * @param {{pagina:number, totalPaginas:number, antesDe:(Node|null),
     *          radio:(number|undefined)}} opciones
     * @returns {HTMLElement|null} la tira
     */
    function pintar(contenedor, opciones) {
        if (!contenedor) return null;
        var o = opciones || {};
        var total = Math.max(1, o.totalPaginas | 0);
        var pagina = Math.min(Math.max(1, o.pagina | 0), total);

        var tira = contenedor.querySelector('[' + ATTR_TIRA + ']');
        if (!tira) {
            tira = document.createElement('div');
            tira.className = 'adhoc-pager-pages';
            tira.setAttribute(ATTR_TIRA, '');
            tira.setAttribute('role', 'group');
            tira.setAttribute('aria-label', 'Páginas');
            // Entre "anterior" y "siguiente", que es donde se espera encontrar
            // los números y donde el orden del tabulador coincide con el
            // visual. Sin ancla válida, al final del contenedor.
            var ancla = (o.antesDe && o.antesDe.parentNode === contenedor) ? o.antesDe : null;
            contenedor.insertBefore(tira, ancla);
        }

        // ¿El foco está en un botón que este repintado va a destruir? Hay que
        // saberlo ANTES de vaciar la tira. Sin esto, activar un número con el
        // teclado devolvía el foco al <body>: el siguiente Tab arrancaba desde
        // "Saltar al contenido" y recorrer la lista con teclado costaba tabular
        // el documento entero por cada cambio de página. Con prev/next el
        // agujero solo se abría en los extremos (al deshabilitarse el botón);
        // con los números pasaba en TODOS los clics, y contradecía la razón por
        // la que `botonPagina` deja habilitado el botón de la página actual —no
        // sacarlo del recorrido del tabulador—.
        var teniaFoco = tira.contains(document.activeElement);
        tira.textContent = '';

        // Con una sola página los números no dicen nada que no diga ya el
        // rótulo, y dejar un "1" pulsable invita a pulsarlo.
        if (total <= 1) {
            tira.hidden = true;
            return tira;
        }
        tira.hidden = false;

        var celdas = ventana(pagina, total, o.radio);
        for (var i = 0; i < celdas.length; i++) {
            tira.appendChild(celdas[i] === null ? elision() : botonPagina(celdas[i], pagina));
        }

        // Y se devuelve al botón de la página en la que se acaba de aterrizar,
        // que es donde el usuario está mirando. `aria-current="page"` es el
        // mismo atributo con el que se marca "estás aquí": no hace falta una
        // segunda forma de identificarlo. `preventScroll` porque la lista ya se
        // ha movido sola al cambiar de página y un salto extra desorienta.
        if (teniaFoco) {
            var actual = tira.querySelector('[aria-current="page"]');
            if (actual) {
                try {
                    actual.focus({ preventScroll: true });
                } catch (e) {
                    actual.focus();
                }
            }
        }
        return tira;
    }

    // ==================== EL ESTADO EN LA URL ====================

    function busqueda() {
        return new URLSearchParams(window.location.search);
    }

    /**
     * Los filtros que vienen EN LA URL, de entre las claves que la pantalla
     * declara en su marcado. Las que no vengan, o vengan vacías, no salen: una
     * clave ausente significa "deja el control como está", no "vacíalo".
     *
     * @param {string[]} claves nombres de filtro que la pantalla reconoce
     * @returns {Object<string,string>}
     */
    function leerFiltros(claves) {
        var params = busqueda();
        var lista = claves || [];
        var out = {};
        for (var i = 0; i < lista.length; i++) {
            var valor = params.get(lista[i]);
            if (valor === null) continue;
            valor = valor.trim();
            if (!valor) continue;
            out[lista[i]] = valor;
        }
        return out;
    }

    /** La página que pide la URL. Cualquier basura vale 1; el tope lo pone el servidor. */
    function leerPagina() {
        var n = parseInt(busqueda().get(PARAM_PAGINA), 10);
        return (isNaN(n) || n < 1) ? 1 : n;
    }

    /**
     * Refleja el estado de la lista en la barra de direcciones.
     *
     * ─── replaceState Y NO pushState ────────────────────────────────────────
     *
     * Es la decisión delicada de todo este archivo, y va en contra de lo que
     * hace la mitad de los paginadores del mundo. La razón es que en esta app
     * el historial NO es nuestro: lo lleva HTMX.
     *
     * `#adhoc-root` va con `hx-boost`, así que cada navegación entre pantallas
     * la empuja HTMX con `history.pushState({htmx: true}, …)` y guarda el DOM
     * de la anterior en `localStorage` bajo la URL que él anotó
     * (`currentPathForHistory`). Al pulsar ATRÁS, su `popstate` solo actúa si
     * la entrada trae `state.htmx`; si actúa, repone desde su caché.
     *
     * Con `pushState` en cada cambio de página tendríamos:
     *
     *   · entradas de historial que HTMX no creó y cuyo `state` no es suyo, así
     *     que su `popstate` las IGNORA: el ATRÁS cambiaría la URL a `?page=4` y
     *     dejaría la página 5 en pantalla. URL y contenido divergiendo es el
     *     síntoma exacto de A10, que el commit 29e9c2f acaba de cerrar;
     *   · o, si añadiéramos nuestro propio `popstate` para taparlo, dos
     *     manejadores del mismo evento peleándose por decidir quién repone
     *     —que es literalmente el fallo que dejó el caché del historial
     *     corrupto y hacía que volver a /adhoc/documentos enseñara el tablero—;
     *   · y doce entradas de basura por lista consultada, de forma que salir de
     *     la pantalla con el ATRÁS pasa a ser doce pulsaciones.
     *
     * `replaceState` no crea entradas, así que no toca nada de eso: el
     * historial sigue teniendo exactamente las entradas que HTMX empujó, en su
     * orden, con su `state` y su caché. Lo único que cambia es la URL de la
     * entrada actual.
     *
     * Se conserva `history.state` a propósito (`replaceState(history.state, …)`
     * y no `replaceState(null, …)`): si esa entrada la empujó HTMX, sigue
     * llevando su `{htmx: true}` y su ATRÁS la sigue restaurando. Pasarle
     * `null` la desheredaría y el ATRÁS dejaría de reponerla.
     *
     * QUÉ PASA AL PULSAR ATRÁS DESPUÉS DE PAGINAR: se sale de la lista, a la
     * pantalla anterior. Paginar y filtrar no son navegaciones, son estados de
     * un mismo listado —igual que ordenar una tabla—, y quien ha puesto tres
     * filtros y ha llegado a la página 6 espera que el ATRÁS lo saque de ahí,
     * no que le deshaga los seis pasos de uno en uno. Lo que sí se conserva es
     * lo que se pedía: esa vista tiene una URL COMPARTIBLE que sobrevive a un
     * F5, porque al cargarla la página y los filtros se leen de ella.
     *
     * Al salir con un enlace boosted, HTMX cachea el DOM bajo la URL que él
     * anotó (la de llegada, sin `?page=6`) y el ATRÁS pide `?page=6`: falla el
     * caché y, con `refreshOnHistoryMiss` en false, HTMX rehace la petición de
     * esa URL. La lista vuelve en su página 6 y recién traída. Cuesta una
     * consulta más que un acierto de caché; a cambio, nunca enseña datos
     * rancios.
     * ────────────────────────────────────────────────────────────────────────
     *
     * Solo se tocan las claves que la pantalla gestiona: lo demás que hubiera
     * en la URL se respeta tal cual, porque puede ser de otro (un `?mode=`, una
     * marca de campaña) y borrárselo sería un efecto colateral invisible.
     *
     * @param {string[]} claves todas las claves de filtro de la pantalla
     * @param {Object<string,string>} valores las que tienen valor ahora mismo
     * @param {number} pagina página actual
     */
    function sincronizar(claves, valores, pagina) {
        if (!window.history || typeof window.history.replaceState !== 'function') return;

        var params = busqueda();
        var lista = claves || [];
        var i;
        for (i = 0; i < lista.length; i++) params.delete(lista[i]);
        params.delete(PARAM_PAGINA);

        var mapa = valores || {};
        for (var clave in mapa) {
            if (!Object.prototype.hasOwnProperty.call(mapa, clave)) continue;
            var valor = mapa[clave];
            if (valor === null || valor === undefined || valor === '') continue;
            params.set(clave, String(valor));
        }

        // La página 1 no se escribe: es el default, y una URL compartida que
        // dice `?page=1` solo añade ruido a lo que hay que leer.
        if (pagina > 1) params.set(PARAM_PAGINA, String(pagina));

        var query = params.toString();
        var url = window.location.pathname + (query ? '?' + query : '') + window.location.hash;
        try {
            window.history.replaceState(window.history.state, '', url);
        } catch (e) {
            // Un navegador puede negarse (cuota del historial, un origen
            // opaco). Que la URL no se actualice no es motivo para dejar la
            // lista a medias.
            console.warn('[adhoc] no se pudo reflejar el estado en la URL:', e);
        }
    }

    window.AdhocPager = {
        RADIO: RADIO,
        PARAM_PAGINA: PARAM_PAGINA,
        ventana: ventana,
        pintar: pintar,
        leerFiltros: leerFiltros,
        leerPagina: leerPagina,
        sincronizar: sincronizar
    };
})();
