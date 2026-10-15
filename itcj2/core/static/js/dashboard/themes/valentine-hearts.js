/**
 * ============================================
 * EFECTO DE SAN VALENTIN - DASHBOARD
 * Corazones flotantes, guirnalda y cupido.
 *
 * Las decoraciones van en #theme-decor (escritorio; dashboard.css la pone detrás
 * o encima de las ventanas según la resolución) o en <body> (móvil). Con
 * prefers-reduced-motion no hay corazones flotantes ni cupido; el bucle se pausa
 * mientras la pestaña está oculta.
 * ============================================
 */

class ValentineHearts {
    constructor(options = {}) {
        // Ajustar cantidad de corazones según el tamaño de pantalla
        const screenWidth = window.innerWidth;
        let defaultHeartCount;
        if (screenWidth <= 480) {
            defaultHeartCount = 8;  // Móvil pequeño
        } else if (screenWidth <= 768) {
            defaultHeartCount = 12; // Móvil/Tablet
        } else if (screenWidth <= 1024) {
            defaultHeartCount = 16; // Tablet grande
        } else {
            defaultHeartCount = 20; // Desktop
        }

        // Velocidades en px por segundo
        this.config = {
            heartCount: options.heartCount || defaultHeartCount,
            minSize: options.minSize || 10,
            maxSize: options.maxSize || 22,
            minSpeed: options.minSpeed || 25,
            maxSpeed: options.maxSpeed || 70,
            heartChars: options.heartChars || ['♥', '♡', '❤', '💕'],
            garlandEnabled: options.garlandEnabled !== false,
            cupidEnabled: options.cupidEnabled !== false,
            enabled: options.enabled !== false
        };

        this.host = document.getElementById('theme-decor') || document.body;
        this.reducedMotion = !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
        this.hearts = [];
        this.animationFrame = null;
        this.isRunning = false;
        this.lastTime = 0;
        this.timers = [];

        if (this.config.enabled) {
            this.init();
        }
    }

    init() {
        // Crear guirnalda de corazones
        if (this.config.garlandEnabled) {
            this.createHeartGarland();
        }

        // Variables para controlar el cupido
        this.cupidActive = false;
        this.cupidTimeout = null;

        // Corazones flotantes y cupido son movimiento puro: fuera con
        // prefers-reduced-motion.
        if (!this.reducedMotion) {
            this.createFloatingHearts();
            this.start();

            if (this.config.cupidEnabled) {
                this.startCupidCycle();
            }

            this.onVisibility = () => {
                if (document.hidden) this.pause();
                else this.start();
            };
            document.addEventListener('visibilitychange', this.onVisibility);
        }

        // Limpiar al salir
        window.addEventListener('beforeunload', () => this.cleanup());
    }

    // ==================== GUIRNALDA DE CORAZONES ====================
    createHeartGarland() {
        const garland = document.createElement('div');
        garland.className = 'valentine-garland';

        // Ajustar cantidad de corazones según el ancho de pantalla
        const screenWidth = window.innerWidth;
        let heartCount;
        if (screenWidth <= 480) {
            heartCount = 8;  // Móvil pequeño
        } else if (screenWidth <= 768) {
            heartCount = 12; // Móvil/Tablet
        } else if (screenWidth <= 1024) {
            heartCount = 18; // Tablet grande
        } else {
            heartCount = 25; // Desktop
        }
        
        const heartSymbols = ['♥', '♡', '❤', '♥', '❣'];

        for (let i = 0; i < heartCount; i++) {
            const heart = document.createElement('div');
            heart.className = 'valentine-heart-light';
            heart.textContent = heartSymbols[i % heartSymbols.length];
            garland.appendChild(heart);
        }

        this.host.appendChild(garland);
        this.garlandEl = garland;
    }

    // ==================== CORAZONES FLOTANTES ====================
    createFloatingHearts() {
        for (let i = 0; i < this.config.heartCount; i++) {
            // Repartidos en toda la altura: sin la "ola" de corazones al cargar.
            this.createHeart(Math.random() * window.innerHeight);
        }
    }

    createHeart(startY = window.innerHeight + 30) {
        const heart = {
            element: document.createElement('div'),
            baseX: Math.random() * window.innerWidth,
            x: 0,
            y: startY,
            size: this.randomBetween(this.config.minSize, this.config.maxSize),
            speed: this.randomBetween(this.config.minSpeed, this.config.maxSpeed),
            drift: this.randomBetween(-12, 12), // deriva horizontal (px/s)
            wobble: Math.random() * Math.PI * 2, // Fase inicial del movimiento ondulante
            wobbleSpeed: this.randomBetween(0.8, 1.8), // rad/s
            wobbleAmount: this.randomBetween(12, 36), // px de vaivén
            rotation: this.randomBetween(-20, 20),
            rotationSpeed: this.randomBetween(-15, 15), // grados por segundo
            maxOpacity: this.randomBetween(0.45, 0.85),
            char: this.config.heartChars[Math.floor(Math.random() * this.config.heartChars.length)]
        };

        heart.element.className = 'floating-heart';
        heart.element.textContent = heart.char;
        heart.element.style.fontSize = `${heart.size.toFixed(1)}px`;
        heart.element.style.color = this.getRandomHeartColor();

        this.host.appendChild(heart.element);
        this.hearts.push(heart);
    }

    getRandomHeartColor() {
        const colors = [
            '#e91e63', '#f44336', '#ff80ab', '#ff5252',
            '#ec407a', '#d81b60', '#f06292', '#ff1744',
            '#ff4081', '#c2185b'
        ];
        return colors[Math.floor(Math.random() * colors.length)];
    }

    updateHearts(dt) {
        const w = window.innerWidth;
        const h = window.innerHeight;
        this.hearts.forEach(heart => {
            // Subir (velocidad negativa en Y porque sube)
            heart.y -= heart.speed * dt;

            // Vaivén horizontal alrededor de una línea que deriva despacio
            heart.wobble += heart.wobbleSpeed * dt;
            heart.baseX += heart.drift * dt;
            if (heart.baseX < -50) {
                heart.baseX = w + 50;
            } else if (heart.baseX > w + 50) {
                heart.baseX = -50;
            }
            heart.x = heart.baseX + Math.sin(heart.wobble) * heart.wobbleAmount;

            // Rotación suave
            heart.rotation += heart.rotationSpeed * dt;

            // Opacidad según la altura: aparece abajo, se desvanece arriba
            const progress = 1 - (heart.y / h);
            let opacity = heart.maxOpacity;
            if (progress < 0.1) {
                opacity *= Math.max(0, progress) * 10; // Fade in
            } else if (progress > 0.85) {
                opacity *= Math.max(0, 1 - progress) * 6.67; // Fade out
            }

            // Escala sutil con el vaivén
            const scale = 0.85 + Math.sin(heart.wobble * 0.5) * 0.15;

            heart.element.style.transform =
                `translate(${heart.x.toFixed(1)}px, ${heart.y.toFixed(1)}px) rotate(${heart.rotation.toFixed(1)}deg) scale(${scale.toFixed(3)})`;
            heart.element.style.opacity = Math.max(0, Math.min(1, opacity)).toFixed(3);

            // Si sale por arriba, reiniciar abajo
            if (heart.y < -50) {
                this.resetHeart(heart);
            }
        });
    }

    resetHeart(heart) {
        heart.baseX = Math.random() * window.innerWidth;
        heart.y = window.innerHeight + 30;
        heart.speed = this.randomBetween(this.config.minSpeed, this.config.maxSpeed);
        heart.drift = this.randomBetween(-12, 12);
        heart.wobble = Math.random() * Math.PI * 2;
        heart.rotation = this.randomBetween(-20, 20);
        heart.char = this.config.heartChars[Math.floor(Math.random() * this.config.heartChars.length)];
        heart.element.textContent = heart.char;
        heart.element.style.color = this.getRandomHeartColor();
    }

    // ==================== CUPIDO ====================
    startCupidCycle() {
        // Primer cupido después de 15 segundos
        this.timers.push(setTimeout(() => this.scheduleNextCupid(), 15000));
    }

    scheduleNextCupid() {
        if (this.cupidActive) return;

        this.createCupid();

        // Ciclo: 2 min visible + animaciones + 4 min espera = ~6 min entre apariciones
        const visibleDuration = 120000; // 2 minutos
        const exitAnimation = 3000;
        const waitBetween = 240000; // 4 minutos

        this.cupidTimeout = setTimeout(() => {
            this.scheduleNextCupid();
        }, visibleDuration + exitAnimation + waitBetween);
    }

    createCupid() {
        if (this.cupidActive) return;

        this.cupidActive = true;

        const container = document.createElement('div');
        container.className = 'cupid-container';

        // Posición aleatoria horizontal
        const side = Math.random() > 0.5 ? 'right' : 'left';
        const horizontalPos = this.randomBetween(10, 30);
        container.style[side] = `${horizontalPos}px`;

        // Cuerpo del cupido
        const body = document.createElement('div');
        body.className = 'cupid-body';

        // Cabeza
        const head = document.createElement('div');
        head.className = 'cupid-head';

        // Ojos
        const eyeLeft = document.createElement('div');
        eyeLeft.className = 'cupid-eye left';
        head.appendChild(eyeLeft);

        const eyeRight = document.createElement('div');
        eyeRight.className = 'cupid-eye right';
        head.appendChild(eyeRight);

        // Mejillas
        const cheekLeft = document.createElement('div');
        cheekLeft.className = 'cupid-cheek left';
        head.appendChild(cheekLeft);

        const cheekRight = document.createElement('div');
        cheekRight.className = 'cupid-cheek right';
        head.appendChild(cheekRight);

        // Sonrisa
        const smile = document.createElement('div');
        smile.className = 'cupid-smile';
        head.appendChild(smile);

        body.appendChild(head);

        // Torso
        const torso = document.createElement('div');
        torso.className = 'cupid-torso';
        body.appendChild(torso);

        // Pañal
        const diaper = document.createElement('div');
        diaper.className = 'cupid-diaper';
        body.appendChild(diaper);

        // Alas
        const wingLeft = document.createElement('div');
        wingLeft.className = 'cupid-wing left';
        body.appendChild(wingLeft);

        const wingRight = document.createElement('div');
        wingRight.className = 'cupid-wing right';
        body.appendChild(wingRight);

        // Arco y flecha
        const bow = document.createElement('div');
        bow.className = 'cupid-bow';
        body.appendChild(bow);

        const arrow = document.createElement('div');
        arrow.className = 'cupid-arrow';
        body.appendChild(arrow);

        // Halo
        const halo = document.createElement('div');
        halo.className = 'cupid-halo';
        body.appendChild(halo);

        container.appendChild(body);
        this.host.appendChild(container);

        // Animación de entrada
        container.classList.add('entering');

        // Después de la entrada, flotar
        this.timers.push(setTimeout(() => {
            container.classList.remove('entering');
            container.classList.add('floating');

            // Disparar flechas periódicamente
            this.startArrowShooting(container);
        }, 3000));

        // Después de 2 minutos, salir
        this.timers.push(setTimeout(() => this.removeCupid(container), 120000));
    }

    startArrowShooting(container) {
        // Disparar una flecha cada 15-25 segundos
        const shoot = () => {
            if (!this.cupidActive || !container.parentNode) return;

            container.classList.add('shooting');

            // Crear corazón de impacto
            const rect = container.getBoundingClientRect();
            this.createShotHeart(rect.left - 50, rect.top + rect.height / 2);

            // Quitar clase shooting y recrear flecha
            setTimeout(() => {
                container.classList.remove('shooting');

                // Recrear la flecha (ya que la animación la hace desaparecer)
                const oldArrow = container.querySelector('.cupid-arrow');
                if (oldArrow) {
                    oldArrow.style.animation = 'none';
                    // Force reflow
                    void oldArrow.offsetHeight;
                    oldArrow.style.animation = '';
                }
            }, 1500);

            // Programar siguiente disparo
            const nextShot = this.randomBetween(15000, 25000);
            if (this.cupidActive && container.parentNode) {
                this.timers.push(setTimeout(shoot, nextShot));
            }
        };

        // Primer disparo después de 5 segundos
        this.timers.push(setTimeout(shoot, 5000));
    }

    createShotHeart(x, y) {
        const heart = document.createElement('div');
        heart.className = 'shot-heart';
        heart.textContent = '♥';
        heart.style.left = `${x}px`;
        heart.style.top = `${y}px`;

        this.host.appendChild(heart);

        // Crear mini corazones que se dispersan
        for (let i = 0; i < 5; i++) {
            const mini = document.createElement('div');
            mini.className = 'shot-heart';
            mini.textContent = '♥';
            mini.style.left = `${x + this.randomBetween(-30, 30)}px`;
            mini.style.top = `${y + this.randomBetween(-20, 20)}px`;
            mini.style.fontSize = `${this.randomBetween(10, 16)}px`;
            mini.style.animationDelay = `${this.randomBetween(0.1, 0.4)}s`;
            this.host.appendChild(mini);

            setTimeout(() => {
                if (mini.parentNode) mini.parentNode.removeChild(mini);
            }, 2000);
        }

        setTimeout(() => {
            if (heart.parentNode) heart.parentNode.removeChild(heart);
        }, 2000);
    }

    removeCupid(container) {
        container.classList.remove('floating');
        container.classList.add('leaving');

        this.timers.push(setTimeout(() => {
            if (container && container.parentNode) {
                container.parentNode.removeChild(container);
            }
            this.cupidActive = false;
        }, 3000));
    }

    // ==================== ANIMACIÓN PRINCIPAL ====================
    animate(now) {
        if (!this.isRunning) return;

        // Paso por tiempo real (no por cuadro): igual en 60 y en 144 Hz; tope de
        // 50 ms para que un tirón no teletransporte los corazones.
        const dt = this.lastTime ? Math.min((now - this.lastTime) / 1000, 0.05) : 0;
        this.lastTime = now;
        this.updateHearts(dt);
        this.animationFrame = requestAnimationFrame((t) => this.animate(t));
    }

    start() {
        if (this.isRunning || this.reducedMotion || !this.hearts.length) return;
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

        // Detener ciclo del cupido
        if (this.cupidTimeout) {
            clearTimeout(this.cupidTimeout);
        }
        this.cupidActive = false;
        if (this.onVisibility) document.removeEventListener('visibilitychange', this.onVisibility);

        // Corazones flotantes, guirnalda, cupido y corazones de disparo
        this.hearts.forEach(heart => heart.element.remove());
        this.hearts = [];
        if (this.garlandEl) this.garlandEl.remove();
        document.querySelectorAll('.cupid-container, .shot-heart').forEach(el => el.remove());
    }

    // ==================== UTILIDADES ====================
    randomBetween(min, max) {
        return Math.random() * (max - min) + min;
    }

    setHeartCount(count) {
        if (this.reducedMotion) return;
        const currentCount = this.hearts.length;

        if (count > currentCount) {
            for (let i = 0; i < count - currentCount; i++) {
                this.createHeart();
            }
            this.start();
        } else if (count < currentCount) {
            const toRemove = currentCount - count;
            for (let i = 0; i < toRemove; i++) {
                const heart = this.hearts.pop();
                if (heart.element && heart.element.parentNode) {
                    heart.element.parentNode.removeChild(heart.element);
                }
            }
        }

        this.config.heartCount = count;
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
        if (deco.hearts?.enabled || deco.garland?.enabled || deco.cupid?.enabled) {
            window.valentineHearts = new ValentineHearts({
                heartCount: deco.hearts?.count || 20,
                minSize: 10,
                maxSize: 22,
                garlandEnabled: deco.garland?.enabled !== false,
                cupidEnabled: deco.cupid?.enabled !== false,
                enabled: deco.hearts?.enabled !== false
            });
        }
    } else {
        // Fallback: comportamiento basado en fechas (por compatibilidad)
        const now = new Date();
        const month = now.getMonth(); // 0-11
        const day = now.getDate();

        // Activar del 1 al 28 de Febrero (mes 1)
        const isValentineSeason = month === 1 && day >= 1 && day <= 28;

        if (isValentineSeason) {
            window.valentineHearts = new ValentineHearts({
                heartCount: 20,
                minSize: 10,
                maxSize: 22,
                garlandEnabled: true,
                cupidEnabled: true,
                enabled: true
            });
        }
    }
});

// ============================================
// CONTROLES OPCIONALES (para debugging)
// ============================================
// valentineHearts.toggle()
// valentineHearts.setHeartCount(40)
// valentineHearts.cleanup()
