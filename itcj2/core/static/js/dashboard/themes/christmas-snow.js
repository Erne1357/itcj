/**
 * ============================================
 * EFECTO DE NIEVE NAVIDEÑA - DASHBOARD
 * Luces, copos que caen, nieve sobre los iconos y muñeco de nieve.
 *
 * Las decoraciones van en #theme-decor (escritorio; dashboard.css la pone detrás
 * o encima de las ventanas según la resolución) o en <body> (móvil). Con
 * prefers-reduced-motion no hay copos ni muñeco; el bucle de los copos se pausa
 * mientras la pestaña está oculta.
 * ============================================
 */

class ChristmasSnow {
    constructor(options = {}) {
        // Ajustar cantidad de copos según el tamaño de pantalla
        const screenWidth = window.innerWidth;
        let defaultSnowflakeCount;
        if (screenWidth <= 480) {
            defaultSnowflakeCount = 12; // Móvil pequeño
        } else if (screenWidth <= 768) {
            defaultSnowflakeCount = 18; // Móvil/Tablet
        } else if (screenWidth <= 1024) {
            defaultSnowflakeCount = 24; // Tablet grande
        } else {
            defaultSnowflakeCount = 30; // Desktop
        }

        // Configuración (velocidades en px por segundo)
        this.config = {
            snowflakeCount: options.snowflakeCount || defaultSnowflakeCount,
            minSize: options.minSize || 10,
            maxSize: options.maxSize || 20,
            minSpeed: options.minSpeed || 35,
            maxSpeed: options.maxSpeed || 90,
            snowflakeChars: options.snowflakeChars || ['❄', '❅', '❆'],
            enabled: options.enabled !== false
        };

        this.host = document.getElementById('theme-decor') || document.body;
        this.reducedMotion = !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
        this.snowflakes = [];
        this.animationFrame = null;
        this.isRunning = false;
        this.lastTime = 0;
        this.timers = [];

        if (this.config.enabled) {
            this.init();
        }
    }

    init() {
        this.createChristmasLights();
        this.addSnowToIcons();

        // Variables para controlar el muñeco de nieve
        this.snowmanActive = false;
        this.snowmanTimeout = null;

        // Copos y muñeco son movimiento puro: fuera con prefers-reduced-motion.
        if (!this.reducedMotion) {
            this.createSnowflakes();
            this.start();
            this.startSnowmanCycle();

            this.onVisibility = () => {
                if (document.hidden) this.pause();
                else this.start();
            };
            document.addEventListener('visibilitychange', this.onVisibility);
        }

        // Limpiar al salir
        window.addEventListener('beforeunload', () => this.cleanup());
    }

    createChristmasLights() {
        const lightsContainer = document.createElement('div');
        lightsContainer.className = 'christmas-lights';

        // Crear SVG para los cables curvos
        const svgNS = "http://www.w3.org/2000/svg";
        const svg = document.createElementNS(svgNS, 'svg');
        svg.setAttribute('class', 'christmas-cables-svg');
        svg.setAttribute('aria-hidden', 'true');
        svg.style.position = 'fixed';
        svg.style.top = '0';
        svg.style.left = '0';
        svg.style.width = '100%';
        svg.style.height = '50px';
        svg.style.pointerEvents = 'none';
        svg.style.zIndex = '9998';

        // Ajustar cantidad de luces según el ancho de pantalla
        const screenWidth = window.innerWidth;
        let lightCount;
        if (screenWidth <= 480) {
            lightCount = 8;  // Móvil pequeño
        } else if (screenWidth <= 768) {
            lightCount = 12; // Móvil/Tablet
        } else if (screenWidth <= 1024) {
            lightCount = 16; // Tablet grande
        } else {
            lightCount = 20; // Desktop
        }

        const lights = [];

        for (let i = 0; i < lightCount; i++) {
            const light = document.createElement('div');
            light.className = 'christmas-light';
            lightsContainer.appendChild(light);
            lights.push(light);
        }

        this.host.appendChild(lightsContainer);
        this.host.appendChild(svg);
        this.lightsEl = lightsContainer;
        this.cablesEl = svg;

        // Esperar a que se rendericen las luces para obtener sus posiciones
        this.timers.push(setTimeout(() => this.createCableCurves(svg, lights), 100));

        // Recrear cables al cambiar tamaño de ventana
        this.onResize = () => {
            clearTimeout(this.resizeTimer);
            this.resizeTimer = setTimeout(() => this.createCableCurves(svg, lights), 120);
        };
        window.addEventListener('resize', this.onResize);
    }

    createCableCurves(svg, lights) {
        // Limpiar cables anteriores
        while (svg.firstChild) svg.removeChild(svg.firstChild);

        const svgNS = "http://www.w3.org/2000/svg";
        const sag = 15; // Cuánto baja el cable en el centro

        // Punto de conexión del cable colgante de cada luz
        const positions = lights.map(light => {
            const rect = light.getBoundingClientRect();
            return { x: rect.left + rect.width / 2, y: rect.top - 12 };
        });
        if (!positions.length) return;

        const addCable = (x1, y1, x2, y2) => {
            const path = document.createElementNS(svgNS, 'path');
            const midX = (x1 + x2) / 2;
            const midY = Math.max(y1, y2) + sag;
            path.setAttribute('d', `M ${x1} ${y1} Q ${midX} ${midY} ${x2} ${y2}`);
            path.setAttribute('stroke', '#2c2c2c');
            path.setAttribute('stroke-width', '2');
            path.setAttribute('fill', 'none');
            path.style.filter = 'drop-shadow(0 1px 2px rgba(0, 0, 0, 0.3))';
            svg.appendChild(path);
        };

        // Desde el borde izquierdo, entre cada par de luces y hasta el borde derecho
        addCable(-100, positions[0].y, positions[0].x, positions[0].y);
        for (let i = 0; i < positions.length - 1; i++) {
            addCable(positions[i].x, positions[i].y, positions[i + 1].x, positions[i + 1].y);
        }
        const last = positions[positions.length - 1];
        addCable(last.x, last.y, window.innerWidth + 100, last.y);
    }

    /**
     * Carámbanos extra sobre la nieve de cada icono. Van DENTRO de la imagen del
     * icono (.desktop-icon-img, position:relative) y son absolutos: el tile no
     * cambia de tamaño y la etiqueta no se mueve. La capa de nieve es CSS.
     */
    addSnowToIcons() {
        document.querySelectorAll('.desktop-icon .desktop-icon-img').forEach((img) => {
            const dripsCount = Math.floor(Math.random() * 2) + 1; // 1-2 goteos extra
            for (let i = 0; i < dripsCount; i++) {
                const drip = document.createElement('span');
                drip.className = 'snow-drip-extra';
                drip.setAttribute('aria-hidden', 'true');
                // Lado derecho (68-80 %) y un poco a la izquierda (8-14 %): el
                // carámbano fijo (::after) va en medio.
                const left = i === 0 ? this.randomBetween(66, 78) : this.randomBetween(8, 14);
                drip.style.left = `${left.toFixed(1)}%`;
                drip.style.width = `${(3 + Math.random()).toFixed(1)}px`;
                drip.style.height = `${(5 + Math.random() * 4).toFixed(1)}px`;
                drip.style.animationDelay = `${(Math.random() * 3).toFixed(2)}s`;
                img.appendChild(drip);
            }
        });
    }

    startSnowmanCycle() {
        // Esperar 10 segundos antes del primer muñeco de nieve
        this.timers.push(setTimeout(() => this.scheduleNextSnowman(), 10000));
    }

    scheduleNextSnowman() {
        // Solo programar si no hay un muñeco activo
        if (this.snowmanActive) return;

        this.createSnowman();

        // El muñeco dura 3 minutos (180000ms) + animación de salida (3000ms);
        // el siguiente llega 3 minutos después de que se vaya.
        const totalCycleDuration = 180000 + 3000;
        const waitBetweenSnowmen = 180000;

        this.snowmanTimeout = setTimeout(() => {
            this.scheduleNextSnowman();
        }, totalCycleDuration + waitBetweenSnowmen);
    }

    createSnowman() {
        if (this.snowmanActive) return;
        this.snowmanActive = true;

        const part = (className, parent) => {
            const el = document.createElement('div');
            el.className = className;
            parent.appendChild(el);
            return el;
        };

        const container = document.createElement('div');
        container.className = 'snowman-container';

        // Bola base (grande)
        part('snowman-ball-bottom', container);

        // Bola media con botones y brazos
        const ballMiddle = part('snowman-ball-middle', container);
        ['btn1', 'btn2', 'btn3'].forEach((btn) => part(`snowman-button ${btn}`, ballMiddle));
        part('snowman-arm left', ballMiddle);
        part('snowman-arm right', ballMiddle);

        // Cabeza: ojos, nariz y sonrisa
        const ballHead = part('snowman-ball-head', container);
        part('snowman-eye left', ballHead);
        part('snowman-eye right', ballHead);
        part('snowman-nose', ballHead);
        part('snowman-smile', ballHead);

        // Sombrero
        part('snowman-hat', container);

        this.host.appendChild(container);

        // Después de que se arme completamente, agregar clase assembled
        this.timers.push(setTimeout(() => container.classList.add('assembled'), 4000));

        // Después de 3 minutos, comenzar a desarmarlo
        this.timers.push(setTimeout(() => this.removeSnowman(container), 180000));
    }

    removeSnowman(container) {
        // Agregar clase leaving para animación de salida
        container.classList.add('leaving');

        // Eliminar del DOM después de que termine la animación (3 segundos)
        this.timers.push(setTimeout(() => {
            if (container && container.parentNode) {
                container.parentNode.removeChild(container);
            }
            // Liberar el flag después de que el muñeco se haya ido completamente
            this.snowmanActive = false;
        }, 3000));
    }

    createSnowflakes() {
        for (let i = 0; i < this.config.snowflakeCount; i++) {
            // Repartidos en toda la altura: sin la "franja" de copos al cargar.
            this.createSnowflake(Math.random() * window.innerHeight);
        }
    }

    createSnowflake(startY = -20) {
        const snowflake = {
            element: document.createElement('div'),
            x: Math.random() * window.innerWidth,
            y: startY,
            size: this.randomBetween(this.config.minSize, this.config.maxSize),
            speed: this.randomBetween(this.config.minSpeed, this.config.maxSpeed),
            drift: this.randomBetween(-15, 15), // Deriva horizontal (px/s)
            sway: Math.random() * Math.PI * 2,
            rotation: Math.random() * 360,
            spin: this.randomBetween(-40, 40), // grados por segundo
            char: this.config.snowflakeChars[Math.floor(Math.random() * this.config.snowflakeChars.length)]
        };

        // Configurar elemento (la posición la pone el transform de cada cuadro)
        snowflake.element.className = 'snowflake';
        snowflake.element.textContent = snowflake.char;
        snowflake.element.style.fontSize = `${snowflake.size}px`;
        snowflake.element.style.opacity = this.randomBetween(0.5, 0.95).toFixed(2);

        this.host.appendChild(snowflake.element);
        this.snowflakes.push(snowflake);
    }

    updateSnowflakes(dt) {
        const w = window.innerWidth;
        const h = window.innerHeight;
        this.snowflakes.forEach((snowflake) => {
            snowflake.y += snowflake.speed * dt;
            snowflake.sway += dt * 1.2;
            snowflake.x += (snowflake.drift + Math.sin(snowflake.sway) * 12) * dt;
            snowflake.rotation += snowflake.spin * dt;

            // Si sale de la pantalla, reiniciar arriba
            if (snowflake.y > h + 20) {
                this.resetSnowflake(snowflake);
            }

            // Si se sale por los lados, entra por el otro
            if (snowflake.x < -50) {
                snowflake.x = w + 50;
            } else if (snowflake.x > w + 50) {
                snowflake.x = -50;
            }

            snowflake.element.style.transform =
                `translate(${snowflake.x.toFixed(1)}px, ${snowflake.y.toFixed(1)}px) rotate(${snowflake.rotation.toFixed(1)}deg)`;
        });
    }

    resetSnowflake(snowflake) {
        snowflake.x = Math.random() * window.innerWidth;
        snowflake.y = -20;
        snowflake.speed = this.randomBetween(this.config.minSpeed, this.config.maxSpeed);
        snowflake.drift = this.randomBetween(-15, 15);
    }

    animate(now) {
        if (!this.isRunning) return;

        // Paso por tiempo real (no por cuadro): igual en 60 y en 144 Hz; tope de
        // 50 ms para que un tirón no teletransporte los copos.
        const dt = this.lastTime ? Math.min((now - this.lastTime) / 1000, 0.05) : 0;
        this.lastTime = now;
        this.updateSnowflakes(dt);
        this.animationFrame = requestAnimationFrame((t) => this.animate(t));
    }

    start() {
        if (this.isRunning || this.reducedMotion || !this.snowflakes.length) return;
        if (document.hidden) return;

        this.isRunning = true;
        this.lastTime = 0;
        this.animationFrame = requestAnimationFrame((t) => this.animate(t));
    }

    /** Detiene el bucle sin quitar nada (pestaña oculta). */
    pause() {
        this.isRunning = false;
        if (this.animationFrame) {
            cancelAnimationFrame(this.animationFrame);
            this.animationFrame = null;
        }
    }

    stop() {
        this.pause();
    }

    toggle() {
        if (this.isRunning) {
            this.stop();
        } else {
            this.start();
        }
    }

    cleanup() {
        this.stop();
        this.timers.forEach(clearTimeout);
        this.timers = [];
        clearTimeout(this.resizeTimer);

        // Cancelar timeout pendiente del muñeco
        if (this.snowmanTimeout) {
            clearTimeout(this.snowmanTimeout);
        }
        this.snowmanActive = false;

        if (this.onVisibility) document.removeEventListener('visibilitychange', this.onVisibility);
        if (this.onResize) window.removeEventListener('resize', this.onResize);

        // Eliminar todos los copos
        this.snowflakes.forEach(snowflake => snowflake.element.remove());
        this.snowflakes = [];

        // Luces, cables, muñeco y carámbanos extra de los iconos
        if (this.lightsEl) this.lightsEl.remove();
        if (this.cablesEl) this.cablesEl.remove();
        document.querySelectorAll('.snowman-container, .snow-drip-extra').forEach(el => el.remove());
    }

    // Utilidades
    randomBetween(min, max) {
        return Math.random() * (max - min) + min;
    }

    // Ajustar cantidad de copos dinámicamente
    setSnowflakeCount(count) {
        if (this.reducedMotion) return;
        const currentCount = this.snowflakes.length;

        if (count > currentCount) {
            for (let i = 0; i < count - currentCount; i++) {
                this.createSnowflake();
            }
            this.start();
        } else if (count < currentCount) {
            for (let i = 0; i < currentCount - count; i++) {
                const snowflake = this.snowflakes.pop();
                snowflake.element.remove();
            }
        }

        this.config.snowflakeCount = count;
    }
}

// ============================================
// INICIALIZACIÓN DINÁMICA POR TEMÁTICA
// ============================================
document.addEventListener('DOMContentLoaded', () => {
    // Verificar si hay una temática activa con decoraciones configuradas
    if (window.activeTheme && window.activeTheme.decorations) {
        const deco = window.activeTheme.decorations;

        // Solo inicializar si las decoraciones están habilitadas
        if (deco.snowflakes?.enabled || deco.lights?.enabled || deco.snowman?.enabled) {
            window.christmasSnow = new ChristmasSnow({
                snowflakeCount: deco.snowflakes?.count || 30,
                minSize: 10,
                maxSize: 20,
                enabled: deco.snowflakes?.enabled !== false
            });
        }
    } else {
        // Fallback: comportamiento original basado en fechas (por compatibilidad)
        const now = new Date();
        const month = now.getMonth(); // 0-11
        const day = now.getDate();

        // Activar en Diciembre (mes 11) o primeros 10 días de Enero (mes 0)
        const isChristmasSeason = month === 11 || (month === 0 && day <= 10);

        if (isChristmasSeason) {
            window.christmasSnow = new ChristmasSnow({
                snowflakeCount: 30,
                minSize: 10,
                maxSize: 20,
                enabled: true
            });
        }
    }
});

// ============================================
// CONTROLES OPCIONALES (para debugging)
// ============================================
// Para activar/desactivar manualmente desde la consola:
// christmasSnow.toggle()
// christmasSnow.setSnowflakeCount(50) // Cambiar cantidad
// christmasSnow.cleanup() // Limpiar todo
