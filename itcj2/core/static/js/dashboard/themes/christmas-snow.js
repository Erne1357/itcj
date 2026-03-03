/**
 * ============================================
 * EFECTO DE NIEVE NAVIDEÑA - DASHBOARD
 * Efecto ligero y optimizado de nieve cayendo
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

        // Configuración
        this.config = {
            snowflakeCount: options.snowflakeCount || defaultSnowflakeCount,
            minSize: options.minSize || 10,
            maxSize: options.maxSize || 20,
            minSpeed: options.minSpeed || 1,
            maxSpeed: options.maxSpeed || 3,
            snowflakeChars: options.snowflakeChars || ['❄', '❅', '❆'],
            enabled: options.enabled !== false
        };

        this.snowflakes = [];
        this.animationFrame = null;
        this.isRunning = false;

        if (this.config.enabled) {
            this.init();
        }
    }

    init() {
        console.log('🎄 Inicializando efecto de nieve navideña...');

        // Crear luces navideñas
        this.createChristmasLights();

        // Agregar nieve en iconos
        this.addSnowToIcons();

        // Crear copos de nieve
        this.createSnowflakes();

        // Iniciar animación
        this.start();

        // Variables para controlar el muñeco de nieve
        this.snowmanActive = false;
        this.snowmanTimeout = null;
        this.snowmanInterval = null;

        // Iniciar muñeco de nieve (aparece cada 3 minutos)
        this.startSnowmanCycle();

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

        document.body.appendChild(lightsContainer);
        document.body.appendChild(svg);

        // Esperar a que se rendericen las luces para obtener sus posiciones
        setTimeout(() => {
            this.createCableCurves(svg, lights);
        }, 100);

        // Recrear cables al cambiar tamaño de ventana
        window.addEventListener('resize', () => {
            this.createCableCurves(svg, lights);
        });
    }

    createCableCurves(svg, lights) {
        // Limpiar cables anteriores
        svg.innerHTML = '';

        const svgNS = "http://www.w3.org/2000/svg";
        const positions = [];

        // Obtener posiciones de todas las luces
        lights.forEach(light => {
            const rect = light.getBoundingClientRect();
            positions.push({
                x: rect.left + rect.width / 2,
                y: rect.top - 12 // Punto de conexión del cable colgante
            });
        });

        // Cable inicial desde el borde izquierdo hasta la primera luz
        if (positions.length > 0) {
            const path = document.createElementNS(svgNS, 'path');
            const startX = -100;
            const startY = positions[0].y;
            const endX = positions[0].x;
            const endY = positions[0].y;
            const sag = 15; // Cuánto baja el cable en el centro

            const midX = (startX + endX) / 2;
            const midY = Math.max(startY, endY) + sag;

            const d = `M ${startX} ${startY} Q ${midX} ${midY} ${endX} ${endY}`;
            path.setAttribute('d', d);
            path.setAttribute('stroke', '#2c2c2c');
            path.setAttribute('stroke-width', '2');
            path.setAttribute('fill', 'none');
            path.style.filter = 'drop-shadow(0 1px 2px rgba(0, 0, 0, 0.3))';
            svg.appendChild(path);
        }

        // Crear cables curvos entre cada par de luces
        for (let i = 0; i < positions.length - 1; i++) {
            const path = document.createElementNS(svgNS, 'path');

            const x1 = positions[i].x;
            const y1 = positions[i].y;
            const x2 = positions[i + 1].x;
            const y2 = positions[i + 1].y;

            // Calcular punto de control para la curva (punto medio más bajo)
            const midX = (x1 + x2) / 2;
            const sag = 15; // Cuánto baja el cable en el centro
            const midY = Math.max(y1, y2) + sag;

            // Crear curva cuadrática (parabólica)
            const d = `M ${x1} ${y1} Q ${midX} ${midY} ${x2} ${y2}`;

            path.setAttribute('d', d);
            path.setAttribute('stroke', '#2c2c2c');
            path.setAttribute('stroke-width', '2');
            path.setAttribute('fill', 'none');
            path.style.filter = 'drop-shadow(0 1px 2px rgba(0, 0, 0, 0.3))';

            svg.appendChild(path);
        }

        // Cable final desde la última luz hasta el borde derecho
        if (positions.length > 0) {
            const path = document.createElementNS(svgNS, 'path');
            const lastPos = positions[positions.length - 1];
            const startX = lastPos.x;
            const startY = lastPos.y;
            const endX = window.innerWidth + 100;
            const endY = lastPos.y;
            const sag = 15;

            const midX = (startX + endX) / 2;
            const midY = Math.max(startY, endY) + sag;

            const d = `M ${startX} ${startY} Q ${midX} ${midY} ${endX} ${endY}`;
            path.setAttribute('d', d);
            path.setAttribute('stroke', '#2c2c2c');
            path.setAttribute('stroke-width', '2');
            path.setAttribute('fill', 'none');
            path.style.filter = 'drop-shadow(0 1px 2px rgba(0, 0, 0, 0.3))';
            svg.appendChild(path);
        }
    }

    addSnowToIcons() {
        const icons = document.querySelectorAll('.desktop-icon');

        icons.forEach((icon, index) => {
            // Agregar goteos adicionales de nieve
            const dripsCount = Math.floor(Math.random() * 2) + 1; // 1-2 goteos extra

            for (let i = 0; i < dripsCount; i++) {
                const drip = document.createElement('div');
                drip.className = 'snow-drip-extra';
                drip.style.left = `${20 + Math.random() * 60}%`;
                drip.style.animationDelay = `${Math.random() * 3}s`;
                drip.style.width = `${2 + Math.random() * 2}px`;
                drip.style.height = `${6 + Math.random() * 4}px`;
                icon.appendChild(drip);
            }
        });
    }

    startSnowmanCycle() {
        // Esperar 10 segundos antes del primer muñeco de nieve
        setTimeout(() => {
            this.scheduleNextSnowman();
        }, 10000); // 10 segundos
    }

    scheduleNextSnowman() {
        // Solo programar si no hay un muñeco activo
        if (this.snowmanActive) {
            console.log('⛄ Ya hay un muñeco activo, esperando...');
            return;
        }

        this.createSnowman();

        // Programar el siguiente después de que termine el ciclo completo
        // El muñeco dura 3 minutos (180000ms) + animación de salida (3000ms)
        // Esperamos 3 minutos después de que se vaya para el siguiente
        const totalCycleDuration = 180000 + 3000; // 3 minutos visible + 3 segundos saliendo
        const waitBetweenSnowmen = 180000; // 3 minutos de espera antes del siguiente

        this.snowmanTimeout = setTimeout(() => {
            this.scheduleNextSnowman();
        }, totalCycleDuration + waitBetweenSnowmen); // Total: 6 minutos entre cada aparición
    }

    createSnowman() {
        // Verificar si ya hay un muñeco activo
        if (this.snowmanActive) {
            console.log('⛄ Ya hay un muñeco de nieve activo, saltando creación...');
            return;
        }

        console.log('⛄ Creando muñeco de nieve...');
        this.snowmanActive = true;

        // Crear contenedor
        const container = document.createElement('div');
        container.className = 'snowman-container';

        // Bola base (grande)
        const ballBottom = document.createElement('div');
        ballBottom.className = 'snowman-ball-bottom';
        container.appendChild(ballBottom);

        // Bola media
        const ballMiddle = document.createElement('div');
        ballMiddle.className = 'snowman-ball-middle';

        // Botones en la bola media
        for (let i = 1; i <= 3; i++) {
            const button = document.createElement('div');
            button.className = `snowman-button btn${i}`;
            ballMiddle.appendChild(button);
        }

        // Brazos
        const armLeft = document.createElement('div');
        armLeft.className = 'snowman-arm left';
        ballMiddle.appendChild(armLeft);

        const armRight = document.createElement('div');
        armRight.className = 'snowman-arm right';
        ballMiddle.appendChild(armRight);

        container.appendChild(ballMiddle);

        // Bola cabeza (pequeña)
        const ballHead = document.createElement('div');
        ballHead.className = 'snowman-ball-head';

        // Ojos
        const eyeLeft = document.createElement('div');
        eyeLeft.className = 'snowman-eye left';
        ballHead.appendChild(eyeLeft);

        const eyeRight = document.createElement('div');
        eyeRight.className = 'snowman-eye right';
        ballHead.appendChild(eyeRight);

        // Nariz
        const nose = document.createElement('div');
        nose.className = 'snowman-nose';
        ballHead.appendChild(nose);

        // Sonrisa
        const smile = document.createElement('div');
        smile.className = 'snowman-smile';
        ballHead.appendChild(smile);

        container.appendChild(ballHead);

        // Sombrero
        const hat = document.createElement('div');
        hat.className = 'snowman-hat';
        container.appendChild(hat);

        // Agregar al DOM
        document.body.appendChild(container);

        // Después de que se arme completamente, agregar clase assembled
        setTimeout(() => {
            container.classList.add('assembled');
        }, 4000);

        // Después de 3 minutos, comenzar a desarmarlo
        setTimeout(() => {
            this.removeSnowman(container);
        }, 180000); // 3 minutos (180 segundos) de permanencia
    }

    removeSnowman(container) {
        console.log('⛄ Despidiendo al muñeco de nieve...');

        // Agregar clase leaving para animación de salida
        container.classList.add('leaving');

        // Eliminar del DOM después de que termine la animación (3 segundos)
        setTimeout(() => {
            if (container && container.parentNode) {
                container.parentNode.removeChild(container);
            }
            // Liberar el flag después de que el muñeco se haya ido completamente
            this.snowmanActive = false;
            console.log('⛄ Muñeco de nieve eliminado. Listo para el siguiente.');
        }, 3000);
    }

    createSnowflakes() {
        for (let i = 0; i < this.config.snowflakeCount; i++) {
            this.createSnowflake();
        }
    }

    createSnowflake() {
        const snowflake = {
            element: document.createElement('div'),
            x: Math.random() * window.innerWidth,
            y: -20,
            size: this.randomBetween(this.config.minSize, this.config.maxSize),
            speed: this.randomBetween(this.config.minSpeed, this.config.maxSpeed),
            drift: this.randomBetween(-0.5, 0.5), // Deriva horizontal
            char: this.config.snowflakeChars[Math.floor(Math.random() * this.config.snowflakeChars.length)]
        };

        // Configurar elemento
        snowflake.element.className = 'snowflake';
        snowflake.element.textContent = snowflake.char;
        snowflake.element.style.left = `${snowflake.x}px`;
        snowflake.element.style.fontSize = `${snowflake.size}px`;
        snowflake.element.style.opacity = this.randomBetween(0.5, 1);

        // Añadir al DOM
        document.body.appendChild(snowflake.element);

        this.snowflakes.push(snowflake);
    }

    updateSnowflakes() {
        this.snowflakes.forEach((snowflake, index) => {
            // Actualizar posición
            snowflake.y += snowflake.speed;
            snowflake.x += snowflake.drift;

            // Aplicar transformación
            snowflake.element.style.transform = `translate(${snowflake.x}px, ${snowflake.y}px)`;

            // Si sale de la pantalla, reiniciar
            if (snowflake.y > window.innerHeight) {
                this.resetSnowflake(snowflake);
            }

            // Si se sale por los lados, ajustar
            if (snowflake.x < -50) {
                snowflake.x = window.innerWidth + 50;
            } else if (snowflake.x > window.innerWidth + 50) {
                snowflake.x = -50;
            }
        });
    }

    resetSnowflake(snowflake) {
        snowflake.x = Math.random() * window.innerWidth;
        snowflake.y = -20;
        snowflake.speed = this.randomBetween(this.config.minSpeed, this.config.maxSpeed);
        snowflake.drift = this.randomBetween(-0.5, 0.5);
    }

    animate() {
        if (!this.isRunning) return;

        this.updateSnowflakes();
        this.animationFrame = requestAnimationFrame(() => this.animate());
    }

    start() {
        if (this.isRunning) return;

        this.isRunning = true;
        this.animate();
        console.log('❄️ Efecto de nieve iniciado');
    }

    stop() {
        this.isRunning = false;
        if (this.animationFrame) {
            cancelAnimationFrame(this.animationFrame);
        }
        console.log('❄️ Efecto de nieve detenido');
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

        // Detener el ciclo del muñeco de nieve
        if (this.snowmanInterval) {
            clearInterval(this.snowmanInterval);
        }
        
        // Cancelar timeout pendiente del muñeco
        if (this.snowmanTimeout) {
            clearTimeout(this.snowmanTimeout);
        }

        // Resetear flag
        this.snowmanActive = false;

        // Eliminar todos los copos
        this.snowflakes.forEach(snowflake => {
            if (snowflake.element && snowflake.element.parentNode) {
                snowflake.element.parentNode.removeChild(snowflake.element);
            }
        });

        // Eliminar luces
        const lights = document.querySelector('.christmas-lights');
        if (lights && lights.parentNode) {
            lights.parentNode.removeChild(lights);
        }

        // Eliminar cables SVG
        const cablesSvg = document.querySelector('.christmas-cables-svg');
        if (cablesSvg && cablesSvg.parentNode) {
            cablesSvg.parentNode.removeChild(cablesSvg);
        }

        // Eliminar muñeco de nieve si existe
        const snowman = document.querySelector('.snowman-container');
        if (snowman && snowman.parentNode) {
            snowman.parentNode.removeChild(snowman);
        }

        // Eliminar goteos de nieve adicionales en los iconos
        const drips = document.querySelectorAll('.snow-drip-extra');
        drips.forEach(drip => {
            if (drip && drip.parentNode) {
                drip.parentNode.removeChild(drip);
            }
        });

        this.snowflakes = [];
        console.log('🎄 Decoraciones navideñas limpiadas');
    }

    // Utilidades
    randomBetween(min, max) {
        return Math.random() * (max - min) + min;
    }

    // Ajustar cantidad de copos dinámicamente
    setSnowflakeCount(count) {
        const currentCount = this.snowflakes.length;

        if (count > currentCount) {
            // Añadir más copos
            for (let i = 0; i < count - currentCount; i++) {
                this.createSnowflake();
            }
        } else if (count < currentCount) {
            // Eliminar copos
            const toRemove = currentCount - count;
            for (let i = 0; i < toRemove; i++) {
                const snowflake = this.snowflakes.pop();
                if (snowflake.element && snowflake.element.parentNode) {
                    snowflake.element.parentNode.removeChild(snowflake.element);
                }
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
                minSpeed: 1,
                maxSpeed: 3,
                enabled: deco.snowflakes?.enabled !== false
            });

            console.log(`🎨 Temática activa: "${window.activeTheme.name}" - Decoraciones habilitadas`);
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
                minSpeed: 1,
                maxSpeed: 3,
                enabled: true
            });

            console.log('🎄 ¡Feliz Navidad! Decoraciones activadas automáticamente (fallback por fechas)');
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
