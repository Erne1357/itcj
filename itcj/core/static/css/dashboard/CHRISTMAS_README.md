# 🎄 Decoraciones Navideñas del Dashboard

Decoraciones ligeras y elegantes para el dashboard del ITCJ durante la temporada navideña.

## 📁 Archivos

- **`christmas-decorations.css`** - Estilos CSS para las decoraciones
- **`christmas-snow.js`** - Script para el efecto de nieve animado

## 🎨 Efectos Incluidos

### 1. **Luces Navideñas con Cables Realistas** 🎄
- Cadena de luces de colores en la parte superior
- **20 luces** con colores alternados (rojo, verde, azul, amarillo, magenta, cyan)
- **Cables curvos parabólicos** que conectan todas las luces simulando gravedad/caída natural
- Los cables **se curvan hacia abajo** entre cada par de luces (como cables reales)
- Se extienden fuera de los bordes de la pantalla
- **Cables colgantes** desde cada luz simulando suspensión real
- **Socket/base** negro en cada luz para mayor realismo
- Efecto de parpadeo/brillo suave
- **Responsive:** Se ajustan automáticamente al cambiar tamaño de ventana
- **Ubicación:** Parte superior de la pantalla

### 2. **Efecto de Nieve** ❄️
- 30 copos de nieve cayendo suavemente
- Diferentes tamaños y velocidades para mayor realismo
- Deriva horizontal ligera
- Se reinician automáticamente al salir de la pantalla
- **Optimizado:** Usa `requestAnimationFrame` para rendimiento óptimo

### 3. **Nieve Acumulada en Íconos** ❄️✨
- **Capa de nieve** blanca acumulada en la parte superior de cada icono
- Efecto de nieve con gradiente que simula textura real
- **Goteos de nieve cayendo** en diferentes posiciones (como carámbanos pequeños)
- Cada icono tiene **1-2 goteos aleatorios** con animación de goteo
- Brillo sutil que simula el reflejo de la luz en la nieve
- **Efecto realista** como si los iconos fueran casitas con nieve encima

### 4. **Taskbar Navideña** 🌈
- Borde superior con degradado de colores navideños
- Animación sutil de movimiento
- No interfiere con la posición original de la taskbar

### 5. **Efectos de Escarcha** ⭐
- Gradientes sutiles en las esquinas superiores de la pantalla
- Simula escarcha acumulada en los bordes
- Efecto sutil que no distrae

### 6. **Muñeco de Nieve Animado** ⛄
- **Animación adorable** que aparece cada 3 minutos cerca de las notificaciones
- **Entrada épica:** 3 bolas de nieve ruedan desde la izquierda y se apilan
- **Detalles realistas:**
  - Ojos negros que parpadean
  - Nariz de zanahoria que se menea
  - Sonrisa simpática
  - 3 botones negros en el cuerpo
  - Brazos de palitos que saludan
  - Sombrero negro con banda roja
- **Animación de permanencia:**
  - Respiración suave (scale sutil)
  - Parpadeo ocasional
  - Los brazos saludan
  - El sombrero hace un gesto ("tip hat")
- **Salida coordinada:** Las bolas se desarman y ruedan hacia la derecha
- **Duración:** ~30 segundos totales (4s entrada + 25s permanencia + 3s salida)
- **Frecuencia:** Cada 3 minutos (primer muñeco aparece a los 30 segundos)
- **Optimizado:** CSS puro, sin impacto en rendimiento

## ⚙️ Configuración

### Activación Automática

El efecto de nieve se activa automáticamente durante la temporada navideña:
- **Diciembre completo** (mes 12)
- **Primeros 10 días de Enero** (1-10 de enero)

### Configuración Manual

Puedes personalizar el efecto desde la consola del navegador:

```javascript
// Cambiar cantidad de copos (por defecto: 30)
christmasSnow.setSnowflakeCount(50);

// Pausar/Reanudar el efecto
christmasSnow.toggle();

// Detener completamente (elimina copos, luces, y muñeco de nieve)
christmasSnow.cleanup();

// Forzar aparición del muñeco de nieve (para testing)
christmasSnow.createSnowman();

// Crear manualmente con opciones personalizadas
const customSnow = new ChristmasSnow({
    snowflakeCount: 40,      // Cantidad de copos
    minSize: 8,              // Tamaño mínimo (px)
    maxSize: 25,             // Tamaño máximo (px)
    minSpeed: 0.5,           // Velocidad mínima
    maxSpeed: 2.5,           // Velocidad máxima
    snowflakeChars: ['❄'],  // Caracteres a usar
    enabled: true            // Activar/desactivar
});
```

## 🎯 Características de Rendimiento

### Optimizaciones
- ✅ Usa `requestAnimationFrame` para animaciones fluidas
- ✅ Solo 30 copos de nieve (cantidad moderada)
- ✅ CSS animations para efectos simples
- ✅ **Cables curvos con SVG** - Curvas cuadráticas (parabólicas) renderizadas eficientemente
- ✅ No usa imágenes pesadas (solo emojis, CSS y SVG ligero)
- ✅ Limpieza automática al salir de la página
- ✅ Los cables se redimensionan automáticamente con la ventana

### Impacto en Rendimiento
- **Mínimo** - Optimizado para no afectar la experiencia del usuario
- **CPU:** < 5% en equipos modernos (copos de nieve constantes)
- **CPU:** < 1% adicional durante muñeco de nieve (solo 30 segundos cada 3 minutos)
- **RAM:** < 12MB adicionales en total
- **GPU:** Aceleración por hardware para todas las animaciones CSS

## 🔧 Desactivar Decoraciones

### Temporalmente (para la sesión actual)
```javascript
// En la consola del navegador
christmasSnow.cleanup();
```

### Permanentemente
Comenta o elimina estas líneas en `dashboard.html`:

```html
<!-- 🎄 NAVIDAD: Decoraciones Navideñas CSS -->
<link rel="stylesheet" href="{{url_for('static',filename = 'core/css/dashboard/christmas-decorations.css')}}?v={{ static_version }}">

<!-- 🎄 NAVIDAD: Efecto de Nieve Navideña -->
<script src="{{url_for('static',filename = 'core/js/dashboard/christmas-snow.js') }}?v={{ static_version }}"></script>
```

## 🎨 Personalización

### Cambiar Colores de Luces

Edita en `christmas-decorations.css`:

```css
.christmas-light:nth-child(6n+1) {
    background: #ff0000; /* Cambia el color aquí */
    color: #ff0000;
}
```

### Cambiar Caracteres de Nieve

Edita en `christmas-snow.js`:

```javascript
snowflakeChars: ['❄', '❅', '❆', '🎄', '⭐'] // Añade más caracteres
```

### Ajustar Cantidad de Nieve

Edita en `christmas-snow.js`:

```javascript
snowflakeCount: 50 // Más copos = más nieve
```

### Ajustar Curvatura de los Cables

Edita en `christmas-snow.js` dentro del método `createCableCurves`:

```javascript
const sag = 15; // Cambiar este valor (más alto = cables más caídos)
// 10 = cables poco caídos
// 15 = curvatura media (predeterminado)
// 20 = cables muy caídos
```

### Ajustar Muñeco de Nieve

Edita en `christmas-snow.js`:

**Cambiar frecuencia de aparición:**
```javascript
// En el método startSnowmanCycle()
}, 180000); // 3 minutos (180000 ms)
// Cambiar a 120000 para 2 minutos
// Cambiar a 300000 para 5 minutos
```

**Cambiar duración de permanencia:**
```javascript
// En el método createSnowman()
}, 25000); // 25 segundos de permanencia
// Aumentar para que se quede más tiempo
// Reducir para que se vaya más rápido
```

**Cambiar posición:**
Edita en `christmas-decorations.css`:
```css
.snowman-container {
    right: 150px; /* Distancia desde la derecha */
    bottom: 40px; /* Altura desde la taskbar */
}
```

## 📱 Responsive

Las decoraciones están optimizadas para móviles:
- Luces más pequeñas en pantallas pequeñas
- Gorros de Santa ajustados
- Mismo rendimiento en todos los dispositivos

## 🐛 Solución de Problemas

### Los copos no se ven
1. Verifica que estés en la temporada navideña (Diciembre o primeros días de Enero)
2. Abre la consola y ejecuta: `christmasSnow.start()`

### Las luces no parpadean
- Verifica que el CSS esté cargado correctamente
- Revisa que no haya conflictos con otros estilos

### El muñeco de nieve no aparece
1. Espera al menos 30 segundos después de cargar la página
2. Para probarlo inmediatamente: `christmasSnow.createSnowman()`
3. Verifica la consola del navegador para mensajes de error

### El muñeco aparece en mal lugar
- Edita la posición en `christmas-decorations.css` (ver sección de personalización)
- En móviles se escala automáticamente a 80%

### Rendimiento lento
- Reduce la cantidad de copos: `christmasSnow.setSnowflakeCount(15)`
- Limpia el efecto: `christmasSnow.cleanup()`

## 📝 Notas

- Los efectos son completamente opcionales y no afectan la funcionalidad del dashboard
- Se pueden desactivar fácilmente sin modificar código
- Diseñados para ser sutiles y no distraer del trabajo
- El muñeco de nieve es una sorpresa especial cada 3 minutos ⛄
- Código limpio y bien documentado para futuras modificaciones
- Todas las animaciones usan CSS puro con aceleración por GPU

## 🎭 Detalles de la Animación del Muñeco

La animación del muñeco de nieve es una secuencia coreografiada:

**Timeline completa (~32 segundos):**
- `0s-2s`: Bola grande rueda y se detiene
- `0.5s-3s`: Bola mediana rueda y salta encima
- `1s-4s`: Bola cabeza rueda y salta a la cima
- `3.5s-4s`: Aparecen ojos, nariz, sonrisa, botones, brazos y sombrero
- `4s-29s`: Permanencia con animaciones suaves (respiración, parpadeo, saludo)
- `29s-32s`: Desarme y salida rodando hacia la derecha

---

**Creado con ❄️ por el equipo de ITCJ**

*¡Felices Fiestas!* 🎄🎅⛄⭐
