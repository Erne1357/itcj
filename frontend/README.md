# ITCJ Frontend - React + TypeScript

Frontend moderno del sistema ITCJ construido con React 18, TypeScript y Vite.

## 🚀 Stack Tecnológico

- **Framework**: React 18.3
- **Language**: TypeScript 5.6
- **Bundler**: Vite 7.3
- **Styling**: Bootstrap 5.3 (a instalar)

## 📋 Requisitos Previos

- Node.js 20+
- npm 10+

## 🛠️ Instalación

```bash
# Instalar dependencias
npm install
```

## 🏃 Comandos de Desarrollo

```bash
# Iniciar servidor de desarrollo (http://localhost:5173)
npm run dev

# Build de producción
npm run build

# Preview del build de producción
npm run preview

# Linting
npm run lint
```

## 🐳 Docker

### Desarrollo con Docker
```bash
# Desde la raíz del proyecto
cd ../
docker-compose -f docker/compose/docker-compose.dev.yml up frontend
```

El frontend estará disponible en: http://localhost:8080 (a través de Nginx)

### Producción con Docker
```bash
# Desde la raíz del proyecto
cd ../
docker-compose -f docker/compose/docker-compose.prod.yml up --build
```

## 📁 Estructura del Proyecto

```
frontend/
├── src/                    # Código fuente
│   ├── assets/            # Imágenes, fuentes, etc.
│   ├── components/        # Componentes reutilizables
│   ├── features/          # Módulos por funcionalidad
│   ├── lib/               # Utilidades y configuración
│   ├── routes/            # Configuración de rutas
│   ├── store/             # Estado global
│   ├── styles/            # Estilos globales
│   ├── types/             # Types de TypeScript
│   ├── App.tsx            # Componente raíz
│   └── main.tsx           # Punto de entrada
├── public/                # Archivos estáticos
├── .env.development       # Variables de entorno dev
├── .env.production        # Variables de entorno prod
├── vite.config.ts         # Configuración de Vite
├── tsconfig.json          # Configuración de TypeScript
└── package.json
```

## 🌍 Variables de Entorno

Las variables de entorno deben tener el prefijo `VITE_` para ser expuestas al cliente.

```bash
# .env.development
VITE_API_BASE_URL=http://localhost:8080/api
VITE_APP_NAME=ITCJ
VITE_MODE=development
```

## 🔗 Proxy de Desarrollo

Vite está configurado para hacer proxy de las siguientes rutas al backend:

- `/api/*` → Backend Flask (APIs REST)
- `/help-desk/*` → Backend Flask (App legacy para iframes)
- `/agendatec/*` → Backend Flask (App legacy para iframes)
- `/static/*` → Backend Flask (Archivos estáticos)

## 📝 Path Aliases

El proyecto está configurado con path aliases para imports más limpios:

```typescript
// En lugar de:
import { Button } from '../../../components/ui/Button'

// Usa:
import { Button } from '@/components/ui/Button'
```

## 🎯 Arquitectura

Este frontend implementa el patrón **Shell + Iframe Container** para migración gradual:

```
┌────────────────────────────────────────┐
│  React Dashboard Shell                 │
│  ┌──────────────────────────────────┐  │
│  │  Header + Navbar (React)         │  │
│  └──────────────────────────────────┘  │
│                                        │
│  ┌──────────────────────────────────┐  │
│  │  Desktop Grid (React)            │  │
│  └──────────────────────────────────┘  │
│                                        │
│  ┌──────────────────────────────────┐  │
│  │  Windows Container               │  │
│  │  ┌──────────┐  ┌──────────────┐ │  │
│  │  │ Window 1 │  │ Window 2     │ │  │
│  │  │ <iframe> │  │ <iframe>     │ │  │
│  │  │ Jinja2   │  │ Jinja2       │ │  │
│  │  └──────────┘  └──────────────┘ │  │
│  └──────────────────────────────────┘  │
│                                        │
│  ┌──────────────────────────────────┐  │
│  │  Taskbar (React)                 │  │
│  └──────────────────────────────────┘  │
└────────────────────────────────────────┘
```

## 📦 Próximas Dependencias a Instalar

Según el plan de migración (PASO 0C):

```bash
# Estado global
npm install zustand

# API y caché
npm install @tanstack/react-query axios

# Routing
npm install react-router-dom
npm install -D @types/react-router-dom

# Formularios
npm install react-hook-form @hookform/resolvers zod

# UI Components
npm install bootstrap@5.3.3 react-bootstrap
npm install lucide-react

# Utilidades
npm install clsx date-fns

# Dev tools
npm install -D eslint-config-prettier prettier
npm install -D vitest @testing-library/react @testing-library/jest-dom
```

## 🧪 Testing

Testing será implementado en fases posteriores con:
- **Vitest** para unit tests
- **React Testing Library** para component tests

## 📚 Recursos

- [Vite Documentation](https://vite.dev/)
- [React Documentation](https://react.dev/)
- [TypeScript Documentation](https://www.typescriptlang.org/)
- [Plan de Migración](../PLAN_MIGRACION_CORE_REACT.md)

---

**Estado**: PASO 0B Completado ✅
**Próximo paso**: PASO 0C - Integración Docker + Dependencias Adicionales
