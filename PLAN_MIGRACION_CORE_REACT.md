# PLAN DE MIGRACIÓN: CORE A REACT
## Sistema ITCJ - Migración Gradual Core → React + Apps en Jinja2

**Fecha:** 2025-12-16
**Estrategia:** Core primero (React) + Apps después (mantener Jinja2)
**Patrón:** Strangler Fig + Iframe Container
**Duración estimada:** 6-8 semanas para Core completo

---

## ÍNDICE

1. [Decisiones Arquitectónicas](#decisiones-arquitectónicas)
2. [Estructura de Proyecto](#estructura-de-proyecto)
3. [Configuración Inicial](#configuración-inicial)
4. [Roadmap Detallado](#roadmap-detallado)
5. [Guías de Implementación](#guías-de-implementación)
6. [Testing y QA](#testing-y-qa)
7. [Deployment](#deployment)
8. [Troubleshooting](#troubleshooting)

---

## DECISIONES ARQUITECTÓNICAS

### 1. Mono-repo vs Multi-repo

#### ✅ DECISIÓN: MONO-REPO (Recomendado)

**Estructura:**
```
ITCJ/  (repositorio existente)
├── frontend/          # NUEVO - Aplicación React
│   ├── src/
│   ├── public/
│   └── package.json
├── itcj/              # Backend Flask existente
│   ├── core/
│   ├── apps/
│   └── ...
├── docker-compose.yml
├── docker-compose.dev.yml
└── README.md
```

**Ventajas del mono-repo:**
- ✅ Historial de Git unificado
- ✅ Cambios coordinados (backend API + frontend) en un commit
- ✅ CI/CD más simple
- ✅ Shared dependencies (Python + Node en un lugar)
- ✅ Feature branches afectan ambos lados
- ✅ Code review unificado
- ✅ No necesitas sincronizar versionado entre repos

**Desventajas (menores):**
- ❌ Repo más pesado (node_modules + venv)
- ❌ CI/CD debe ejecutar ambos pipelines

**Alternativa multi-repo (NO recomendado):**
```
ITCJ-backend/     (Flask)
ITCJ-frontend/    (React)
```
Problemas:
- Sincronización de cambios entre repos
- Versionado complejo
- CI/CD duplicado
- Pull requests separados
- Más overhead de gestión

---

### 2. Arquitectura Híbrida: React Core + Jinja2 Apps

#### Patrón: Shell + Iframe Container

```
┌────────────────────────────────────────────────────────┐
│                  REACT DASHBOARD SHELL                 │
│  ┌──────────────────────────────────────────────────┐  │
│  │  Header + Navbar (React)                         │  │
│  │  - User menu, Notifications, Search              │  │
│  └──────────────────────────────────────────────────┘  │
│                                                        │
│  ┌──────────────────────────────────────────────────┐  │
│  │  Desktop Grid (React - Windows-like UI)          │  │
│  │  - App icons (AgendaTec, Helpdesk, Config)       │  │
│  │  - Badge notifications                            │  │
│  └──────────────────────────────────────────────────┘  │
│                                                        │
│  ┌──────────────────────────────────────────────────┐  │
│  │  Windows Container (React)                        │  │
│  │                                                   │  │
│  │  ┌─────────────────────┐  ┌──────────────────┐  │  │
│  │  │ Window 1 (React)    │  │ Window 2 (React) │  │  │
│  │  │ ┌─────────────────┐ │  │ ┌──────────────┐ │  │  │
│  │  │ │ <iframe>        │ │  │ │ <iframe>     │ │  │  │
│  │  │ │ /help-desk/     │ │  │ │ /agendatec/  │ │  │  │
│  │  │ │ (Jinja2 app)    │ │  │ │ (Jinja2 app) │ │  │  │
│  │  │ └─────────────────┘ │  │ └──────────────┘ │  │  │
│  │  └─────────────────────┘  └──────────────────┘  │  │
│  └──────────────────────────────────────────────────┘  │
│                                                        │
│  ┌──────────────────────────────────────────────────┐  │
│  │  Taskbar (React)                                  │  │
│  │  - Start menu, Open apps, System tray            │  │
│  └──────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────┘

               ↓ API Calls (Fetch with credentials)

┌────────────────────────────────────────────────────────┐
│              FLASK BACKEND (Sin cambios)               │
│  ┌──────────────────────────────────────────────────┐  │
│  │  /api/core/v1/      - Core APIs                  │  │
│  │  /api/help-desk/v1/ - Helpdesk APIs              │  │
│  │  /api/agendatec/v1/ - AgendaTec APIs             │  │
│  │                                                   │  │
│  │  /help-desk/*       - Jinja2 pages (iframes)     │  │
│  │  /agendatec/*       - Jinja2 pages (iframes)     │  │
│  └──────────────────────────────────────────────────┘  │
│                                                        │
│  JWT Cookie: itcj_token (HttpOnly, SameSite, Secure)  │
└────────────────────────────────────────────────────────┘
```

**Ventajas de este enfoque:**
1. ✅ **Apps sin cambios** - Helpdesk y AgendaTec siguen funcionando EXACTAMENTE igual
2. ✅ **Migración gradual** - Core en React, apps después
3. ✅ **Patrón ya existente** - Dashboard actual YA usa iframes
4. ✅ **Seguridad** - Iframe sandbox aísla apps
5. ✅ **Auth compartida** - JWT cookie accesible en iframe
6. ✅ **Sin deuda técnica** - Migrar apps después es directo

---

### 3. Stack Tecnológico

#### Frontend (React Core)

```json
{
  "framework": "React 18.2",
  "language": "TypeScript 5.3",
  "bundler": "Vite 5.0",
  "state": "Zustand 4.4",
  "api": "TanStack Query 5.0",
  "router": "React Router 6.20",
  "forms": "react-hook-form 7.49 + zod 3.22",
  "ui": "Bootstrap 5.3 (mantener actual) + Radix UI",
  "icons": "Lucide React 0.300",
  "testing": "Vitest 1.0 + React Testing Library",
  "linting": "ESLint + Prettier"
}
```

#### Backend (Sin cambios)

```
Flask 3.1.1
SQLAlchemy 2.0.43
PostgreSQL 14+
Redis 7 (WebSocket broker)
```

---

## ESTRUCTURA DE PROYECTO

### Estructura Final

```
ITCJ/
├── frontend/                          # NUEVA - Aplicación React
│   ├── public/
│   │   ├── favicon.ico
│   │   └── index.html
│   │
│   ├── src/
│   │   ├── main.tsx                   # Entry point
│   │   ├── App.tsx                    # Root component
│   │   │
│   │   ├── assets/                    # Imágenes, fuentes
│   │   │   ├── images/
│   │   │   └── fonts/
│   │   │
│   │   ├── components/                # Componentes reutilizables
│   │   │   ├── ui/                    # UI primitivos
│   │   │   │   ├── Button.tsx
│   │   │   │   ├── Modal.tsx
│   │   │   │   ├── Input.tsx
│   │   │   │   ├── Select.tsx
│   │   │   │   ├── Table.tsx
│   │   │   │   └── index.ts
│   │   │   │
│   │   │   ├── layout/                # Layout components
│   │   │   │   ├── Shell.tsx
│   │   │   │   ├── Header.tsx
│   │   │   │   ├── Sidebar.tsx
│   │   │   │   └── Footer.tsx
│   │   │   │
│   │   │   └── shared/                # Componentes compartidos
│   │   │       ├── LoadingSpinner.tsx
│   │   │       ├── ErrorBoundary.tsx
│   │   │       └── Toast.tsx
│   │   │
│   │   ├── features/                  # Feature-based modules
│   │   │   │
│   │   │   ├── auth/                  # Autenticación
│   │   │   │   ├── components/
│   │   │   │   │   ├── LoginForm.tsx
│   │   │   │   │   └── LogoutButton.tsx
│   │   │   │   ├── hooks/
│   │   │   │   │   ├── useAuth.ts
│   │   │   │   │   └── useLogin.ts
│   │   │   │   ├── api/
│   │   │   │   │   └── authApi.ts
│   │   │   │   ├── store/
│   │   │   │   │   └── authStore.ts
│   │   │   │   ├── types/
│   │   │   │   │   └── auth.types.ts
│   │   │   │   └── pages/
│   │   │   │       └── LoginPage.tsx
│   │   │   │
│   │   │   ├── dashboard/             # Dashboard Windows-like
│   │   │   │   ├── components/
│   │   │   │   │   ├── DesktopGrid.tsx
│   │   │   │   │   ├── AppIcon.tsx
│   │   │   │   │   ├── Window.tsx
│   │   │   │   │   ├── WindowManager.tsx
│   │   │   │   │   ├── Taskbar.tsx
│   │   │   │   │   ├── StartMenu.tsx
│   │   │   │   │   └── SystemTray.tsx
│   │   │   │   ├── hooks/
│   │   │   │   │   ├── useWindows.ts
│   │   │   │   │   └── useTutorial.ts
│   │   │   │   ├── store/
│   │   │   │   │   └── windowStore.ts
│   │   │   │   ├── types/
│   │   │   │   │   └── window.types.ts
│   │   │   │   └── pages/
│   │   │   │       └── DashboardPage.tsx
│   │   │   │
│   │   │   ├── notifications/         # Sistema de notificaciones
│   │   │   │   ├── components/
│   │   │   │   │   ├── NotificationBell.tsx
│   │   │   │   │   ├── NotificationList.tsx
│   │   │   │   │   └── NotificationItem.tsx
│   │   │   │   ├── hooks/
│   │   │   │   │   ├── useNotifications.ts
│   │   │   │   │   └── useSSE.ts
│   │   │   │   ├── api/
│   │   │   │   │   └── notificationsApi.ts
│   │   │   │   └── store/
│   │   │   │       └── notificationStore.ts
│   │   │   │
│   │   │   ├── profile/               # Perfil de usuario
│   │   │   │   ├── components/
│   │   │   │   │   ├── ProfileMenu.tsx
│   │   │   │   │   ├── ProfileForm.tsx
│   │   │   │   │   └── PasswordChange.tsx
│   │   │   │   ├── hooks/
│   │   │   │   │   └── useProfile.ts
│   │   │   │   ├── api/
│   │   │   │   │   └── profileApi.ts
│   │   │   │   └── pages/
│   │   │   │       └── ProfilePage.tsx
│   │   │   │
│   │   │   └── config/                # Páginas de configuración
│   │   │       ├── components/
│   │   │       │   ├── UserTable.tsx
│   │   │       │   ├── RoleTable.tsx
│   │   │       │   ├── DepartmentTable.tsx
│   │   │       │   └── PermissionTable.tsx
│   │   │       ├── hooks/
│   │   │       │   ├── useUsers.ts
│   │   │       │   ├── useRoles.ts
│   │   │       │   └── useDepartments.ts
│   │   │       ├── api/
│   │   │       │   └── configApi.ts
│   │   │       └── pages/
│   │   │           ├── UsersPage.tsx
│   │   │           ├── RolesPage.tsx
│   │   │           ├── DepartmentsPage.tsx
│   │   │           └── PermissionsPage.tsx
│   │   │
│   │   ├── lib/                       # Utilidades compartidas
│   │   │   ├── api/
│   │   │   │   ├── client.ts          # Axios/Fetch configurado
│   │   │   │   ├── queryClient.ts     # TanStack Query setup
│   │   │   │   └── interceptors.ts    # Auth interceptor
│   │   │   │
│   │   │   ├── utils/
│   │   │   │   ├── date.ts
│   │   │   │   ├── format.ts
│   │   │   │   ├── validation.ts
│   │   │   │   └── constants.ts
│   │   │   │
│   │   │   └── hooks/                 # Hooks compartidos
│   │   │       ├── useDebounce.ts
│   │   │       ├── useLocalStorage.ts
│   │   │       └── useMediaQuery.ts
│   │   │
│   │   ├── routes/                    # Configuración de rutas
│   │   │   ├── index.tsx              # Router principal
│   │   │   ├── ProtectedRoute.tsx     # Guard de autenticación
│   │   │   └── routes.config.ts       # Definición de rutas
│   │   │
│   │   ├── store/                     # Estado global (Zustand)
│   │   │   ├── index.ts               # Export all stores
│   │   │   └── middleware/
│   │   │       └── logger.ts
│   │   │
│   │   ├── types/                     # Types globales
│   │   │   ├── api.types.ts
│   │   │   ├── user.types.ts
│   │   │   └── index.ts
│   │   │
│   │   └── styles/                    # Estilos globales
│   │       ├── global.css
│   │       ├── variables.css
│   │       └── themes/
│   │
│   ├── .env.development               # Variables de entorno dev
│   ├── .env.production                # Variables de entorno prod
│   ├── .eslintrc.json                 # ESLint config
│   ├── .prettierrc                    # Prettier config
│   ├── tsconfig.json                  # TypeScript config
│   ├── vite.config.ts                 # Vite config
│   ├── package.json
│   └── README.md
│
├── itcj/                              # Backend Flask (EXISTENTE)
│   ├── core/
│   │   ├── models/
│   │   ├── routes/
│   │   │   ├── api/                   # APIs (sin cambios)
│   │   │   └── pages/                 # ⚠️ A deprecar gradualmente
│   │   ├── services/
│   │   ├── static/                    # ⚠️ A migrar/deprecar
│   │   ├── templates/                 # ⚠️ A deprecar
│   │   └── utils/
│   │
│   ├── apps/
│   │   ├── helpdesk/                  # Mantener SIN cambios
│   │   │   ├── routes/
│   │   │   ├── static/
│   │   │   └── templates/
│   │   │
│   │   └── agendatec/                 # Mantener SIN cambios
│   │       ├── routes/
│   │       ├── static/
│   │       └── templates/
│   │
│   ├── config.py
│   ├── extensions.py
│   └── __init__.py
│
├── docker/
│   ├── Dockerfile.backend
│   ├── Dockerfile.frontend
│   └── nginx.conf
│
├── docker-compose.yml                 # Producción
├── docker-compose.dev.yml             # Desarrollo
├── .gitignore
└── README.md
```

---

## CONFIGURACIÓN INICIAL

### PASO 0: Setup del Proyecto React (Semana 1, Días 1-2)

#### 1. Crear carpeta frontend

```bash
cd ITCJ/
mkdir frontend
cd frontend
```

#### 2. Inicializar proyecto Vite + React + TypeScript

```bash
npm create vite@latest . -- --template react-ts
```

**Resultado:**
```
frontend/
├── src/
│   ├── App.tsx
│   ├── main.tsx
│   └── vite-env.d.ts
├── public/
├── index.html
├── package.json
├── tsconfig.json
└── vite.config.ts
```

#### 3. Instalar dependencias core

```bash
npm install

# State management
npm install zustand

# API
npm install @tanstack/react-query axios

# Router
npm install react-router-dom

# Forms
npm install react-hook-form @hookform/resolvers zod

# UI
npm install bootstrap@5.3.3 react-bootstrap
npm install lucide-react

# Utils
npm install clsx date-fns

# Dev dependencies
npm install -D @types/node
npm install -D eslint-config-prettier prettier
npm install -D vitest @testing-library/react @testing-library/jest-dom
```

#### 4. Configurar Vite

```typescript
// frontend/vite.config.ts
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  plugins: [react()],

  server: {
    port: 3000,
    proxy: {
      // Proxy API requests a Flask backend
      '/api': {
        target: 'http://localhost:5000',
        changeOrigin: true,
      },
      // Proxy app routes (para iframes)
      '/help-desk': {
        target: 'http://localhost:5000',
        changeOrigin: true,
      },
      '/agendatec': {
        target: 'http://localhost:5000',
        changeOrigin: true,
      },
    },
  },

  build: {
    outDir: 'dist',
    emptyOutDir: true,
    sourcemap: true,
  },

  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
})
```

#### 5. Configurar TypeScript

```json
// frontend/tsconfig.json
{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,

    /* Bundler mode */
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx",

    /* Linting */
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true,

    /* Path mapping */
    "baseUrl": ".",
    "paths": {
      "@/*": ["./src/*"]
    }
  },
  "include": ["src"],
  "references": [{ "path": "./tsconfig.node.json" }]
}
```

#### 6. Configurar ESLint + Prettier

```json
// frontend/.eslintrc.json
{
  "extends": [
    "eslint:recommended",
    "plugin:@typescript-eslint/recommended",
    "plugin:react/recommended",
    "plugin:react-hooks/recommended",
    "prettier"
  ],
  "parser": "@typescript-eslint/parser",
  "parserOptions": {
    "ecmaVersion": "latest",
    "sourceType": "module",
    "ecmaFeatures": {
      "jsx": true
    }
  },
  "rules": {
    "react/react-in-jsx-scope": "off",
    "@typescript-eslint/no-unused-vars": ["warn", { "argsIgnorePattern": "^_" }]
  },
  "settings": {
    "react": {
      "version": "detect"
    }
  }
}
```

```json
// frontend/.prettierrc
{
  "semi": true,
  "trailingComma": "es5",
  "singleQuote": true,
  "printWidth": 100,
  "tabWidth": 2,
  "useTabs": false
}
```

#### 7. Variables de entorno

```bash
# frontend/.env.development
VITE_API_BASE_URL=http://localhost:5000/api
VITE_APP_NAME=ITCJ
```

```bash
# frontend/.env.production
VITE_API_BASE_URL=/api
VITE_APP_NAME=ITCJ
```

#### 8. Actualizar .gitignore

```bash
# Agregar al .gitignore raíz
echo "
# Frontend
frontend/node_modules/
frontend/dist/
frontend/.env.local
" >> .gitignore
```

#### 9. Actualizar Docker Compose (Desarrollo)

```yaml
# docker-compose.dev.yml
version: '3.8'

services:
  # NUEVO - Frontend React
  frontend:
    image: node:20-alpine
    container_name: itcj-frontend-dev
    working_dir: /app
    volumes:
      - ./frontend:/app
      - /app/node_modules  # No montar node_modules del host
    ports:
      - "3000:3000"
    command: npm run dev -- --host 0.0.0.0
    environment:
      - VITE_API_BASE_URL=http://backend:8000/api
    depends_on:
      - backend
    networks:
      - itcj-network

  # Backend Flask (EXISTENTE - sin cambios mayores)
  backend:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: itcj-backend-dev
    volumes:
      - ./itcj:/app/itcj
      - ./instance:/app/instance
    ports:
      - "5000:8000"
    environment:
      - FLASK_ENV=development
      - FLASK_DEBUG=1
      - DATABASE_URL=postgresql://user:pass@postgres:5432/itcj_dev
      - REDIS_URL=redis://redis:6379/0
    depends_on:
      - postgres
      - redis
    command: flask run --host=0.0.0.0 --port=8000 --reload
    networks:
      - itcj-network

  # PostgreSQL (SIN CAMBIOS)
  postgres:
    image: postgres:14-alpine
    container_name: itcj-postgres
    environment:
      - POSTGRES_DB=itcj_dev
      - POSTGRES_USER=user
      - POSTGRES_PASSWORD=pass
    volumes:
      - postgres_data:/var/lib/postgresql/data
    ports:
      - "5432:5432"
    networks:
      - itcj-network

  # Redis (SIN CAMBIOS)
  redis:
    image: redis:7-alpine
    container_name: itcj-redis
    ports:
      - "6379:6379"
    networks:
      - itcj-network

networks:
  itcj-network:
    driver: bridge

volumes:
  postgres_data:
```

#### 10. Verificar setup

```bash
# Terminal 1: Backend (desde raíz)
docker-compose -f docker-compose.dev.yml up backend postgres redis

# Terminal 2: Frontend (desde frontend/)
cd frontend
npm run dev
```

**Verificar:**
- ✅ Backend: http://localhost:5000/health
- ✅ Frontend: http://localhost:3000
- ✅ Proxy funcionando: http://localhost:3000/api/core/v1/user/me (debería llamar a Flask)

---

## ROADMAP DETALLADO

### SEMANA 1: Setup + Infraestructura

#### Día 1-2: Configuración inicial (Completado arriba)
- ✅ Crear proyecto React con Vite
- ✅ Instalar dependencias
- ✅ Configurar TypeScript, ESLint, Prettier
- ✅ Docker Compose con frontend + backend

#### Día 3-4: API Client + Auth Hooks

**1. Configurar Axios**

```typescript
// frontend/src/lib/api/client.ts
import axios from 'axios';

const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api',
  withCredentials: true, // CRÍTICO: Incluir cookies JWT
  headers: {
    'Content-Type': 'application/json',
  },
});

// Interceptor para manejar errores globalmente
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      // Usuario no autenticado, redirect a login
      window.location.href = '/login';
    }
    return Promise.reject(error);
  }
);

export { apiClient };
```

**2. Configurar TanStack Query**

```typescript
// frontend/src/lib/api/queryClient.ts
import { QueryClient } from '@tanstack/react-query';

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
      staleTime: 5 * 60 * 1000, // 5 minutos
    },
  },
});
```

**3. Auth API**

```typescript
// frontend/src/features/auth/api/authApi.ts
import { apiClient } from '@/lib/api/client';

export interface LoginCredentials {
  username: string;
  password: string;
}

export interface User {
  sub: number;
  cn: string;
  name: string;
  role: string[];
}

export const authApi = {
  login: async (credentials: LoginCredentials) => {
    const response = await apiClient.post('/core/v1/auth/login', credentials);
    return response.data;
  },

  getCurrentUser: async (): Promise<User> => {
    const response = await apiClient.get('/core/v1/auth/me');
    return response.data.user;
  },

  logout: async () => {
    await apiClient.post('/core/v1/auth/logout');
  },
};
```

**4. Auth Store (Zustand)**

```typescript
// frontend/src/features/auth/store/authStore.ts
import { create } from 'zustand';
import { User } from '../api/authApi';

interface AuthState {
  user: User | null;
  isAuthenticated: boolean;
  setUser: (user: User | null) => void;
  logout: () => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  isAuthenticated: false,

  setUser: (user) => set({
    user,
    isAuthenticated: !!user
  }),

  logout: () => set({
    user: null,
    isAuthenticated: false
  }),
}));
```

**5. Auth Hook**

```typescript
// frontend/src/features/auth/hooks/useAuth.ts
import { useQuery } from '@tanstack/react-query';
import { authApi } from '../api/authApi';
import { useAuthStore } from '../store/authStore';
import { useEffect } from 'react';

export const useAuth = () => {
  const { user, isAuthenticated, setUser } = useAuthStore();

  const { data, isLoading, error } = useQuery({
    queryKey: ['auth', 'current-user'],
    queryFn: authApi.getCurrentUser,
    retry: false,
  });

  useEffect(() => {
    if (data) {
      setUser(data);
    }
  }, [data, setUser]);

  return {
    user,
    isAuthenticated,
    isLoading,
    error,
  };
};
```

#### Día 5: UI Components Base

**1. Button Component**

```typescript
// frontend/src/components/ui/Button.tsx
import { ButtonHTMLAttributes, forwardRef } from 'react';
import clsx from 'clsx';

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'danger' | 'success';
  size?: 'sm' | 'md' | 'lg';
  isLoading?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ variant = 'primary', size = 'md', isLoading, className, children, ...props }, ref) => {
    return (
      <button
        ref={ref}
        className={clsx(
          'btn',
          `btn-${variant}`,
          `btn-${size}`,
          isLoading && 'disabled',
          className
        )}
        disabled={isLoading || props.disabled}
        {...props}
      >
        {isLoading ? (
          <>
            <span className="spinner-border spinner-border-sm me-2" />
            Cargando...
          </>
        ) : (
          children
        )}
      </button>
    );
  }
);

Button.displayName = 'Button';
```

**2. Modal Component**

```typescript
// frontend/src/components/ui/Modal.tsx
import { ReactNode, useEffect } from 'react';
import { createPortal } from 'react-dom';
import { X } from 'lucide-react';

interface ModalProps {
  isOpen: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  size?: 'sm' | 'md' | 'lg' | 'xl';
}

export const Modal = ({ isOpen, onClose, title, children, size = 'md' }: ModalProps) => {
  useEffect(() => {
    if (isOpen) {
      document.body.style.overflow = 'hidden';
    } else {
      document.body.style.overflow = 'unset';
    }
    return () => {
      document.body.style.overflow = 'unset';
    };
  }, [isOpen]);

  if (!isOpen) return null;

  return createPortal(
    <>
      <div className="modal-backdrop fade show" onClick={onClose} />
      <div className="modal fade show d-block" tabIndex={-1}>
        <div className={`modal-dialog modal-${size} modal-dialog-centered`}>
          <div className="modal-content">
            <div className="modal-header">
              <h5 className="modal-title">{title}</h5>
              <button
                type="button"
                className="btn-close"
                onClick={onClose}
                aria-label="Close"
              />
            </div>
            <div className="modal-body">{children}</div>
          </div>
        </div>
      </div>
    </>,
    document.body
  );
};
```

**3. Input Component**

```typescript
// frontend/src/components/ui/Input.tsx
import { InputHTMLAttributes, forwardRef } from 'react';
import clsx from 'clsx';

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  error?: string;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ label, error, className, ...props }, ref) => {
    return (
      <div className="mb-3">
        {label && (
          <label className="form-label" htmlFor={props.id}>
            {label}
          </label>
        )}
        <input
          ref={ref}
          className={clsx('form-control', error && 'is-invalid', className)}
          {...props}
        />
        {error && <div className="invalid-feedback">{error}</div>}
      </div>
    );
  }
);

Input.displayName = 'Input';
```

---

### SEMANA 2: Login + Routing

#### Día 1-2: Login Page

**1. Login Form Component**

```typescript
// frontend/src/features/auth/components/LoginForm.tsx
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { useMutation } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { authApi } from '../api/authApi';
import { useAuthStore } from '../store/authStore';
import { Input } from '@/components/ui/Input';
import { Button } from '@/components/ui/Button';

const loginSchema = z.object({
  username: z.string().min(1, 'Usuario requerido'),
  password: z.string().min(1, 'Contraseña requerida'),
});

type LoginFormData = z.infer<typeof loginSchema>;

export const LoginForm = () => {
  const navigate = useNavigate();
  const setUser = useAuthStore((state) => state.setUser);

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<LoginFormData>({
    resolver: zodResolver(loginSchema),
  });

  const loginMutation = useMutation({
    mutationFn: authApi.login,
    onSuccess: (data) => {
      setUser(data.user);
      navigate('/dashboard');
    },
    onError: () => {
      alert('Credenciales inválidas');
    },
  });

  const onSubmit = (data: LoginFormData) => {
    loginMutation.mutate(data);
  };

  return (
    <form onSubmit={handleSubmit(onSubmit)}>
      <Input
        id="username"
        label="Usuario"
        type="text"
        {...register('username')}
        error={errors.username?.message}
      />

      <Input
        id="password"
        label="Contraseña"
        type="password"
        {...register('password')}
        error={errors.password?.message}
      />

      <Button type="submit" className="w-100" isLoading={loginMutation.isPending}>
        Iniciar Sesión
      </Button>
    </form>
  );
};
```

**2. Login Page**

```typescript
// frontend/src/features/auth/pages/LoginPage.tsx
import { LoginForm } from '../components/LoginForm';

export const LoginPage = () => {
  return (
    <div className="container">
      <div className="row justify-content-center align-items-center min-vh-100">
        <div className="col-md-5">
          <div className="card shadow">
            <div className="card-body p-5">
              <div className="text-center mb-4">
                <h1 className="h3 mb-3 fw-bold">ITCJ</h1>
                <p className="text-muted">Inicia sesión en tu cuenta</p>
              </div>
              <LoginForm />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
```

#### Día 3-4: Routing + Protected Routes

**1. Router Configuration**

```typescript
// frontend/src/routes/index.tsx
import { createBrowserRouter, Navigate } from 'react-router-dom';
import { LoginPage } from '@/features/auth/pages/LoginPage';
import { DashboardPage } from '@/features/dashboard/pages/DashboardPage';
import { ProfilePage } from '@/features/profile/pages/ProfilePage';
import { ProtectedRoute } from './ProtectedRoute';

export const router = createBrowserRouter([
  {
    path: '/login',
    element: <LoginPage />,
  },
  {
    path: '/',
    element: <Navigate to="/dashboard" replace />,
  },
  {
    path: '/dashboard',
    element: (
      <ProtectedRoute>
        <DashboardPage />
      </ProtectedRoute>
    ),
  },
  {
    path: '/profile',
    element: (
      <ProtectedRoute>
        <ProfilePage />
      </ProtectedRoute>
    ),
  },
  // TODO: Agregar rutas de config después
]);
```

**2. Protected Route Component**

```typescript
// frontend/src/routes/ProtectedRoute.tsx
import { ReactNode } from 'react';
import { Navigate } from 'react-router-dom';
import { useAuth } from '@/features/auth/hooks/useAuth';

interface ProtectedRouteProps {
  children: ReactNode;
}

export const ProtectedRoute = ({ children }: ProtectedRouteProps) => {
  const { isAuthenticated, isLoading } = useAuth();

  if (isLoading) {
    return (
      <div className="d-flex justify-content-center align-items-center min-vh-100">
        <div className="spinner-border" role="status">
          <span className="visually-hidden">Cargando...</span>
        </div>
      </div>
    );
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  return <>{children}</>;
};
```

**3. App Root**

```typescript
// frontend/src/App.tsx
import { QueryClientProvider } from '@tanstack/react-query';
import { RouterProvider } from 'react-router-dom';
import { queryClient } from '@/lib/api/queryClient';
import { router } from '@/routes';

export const App = () => {
  return (
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  );
};
```

**4. Main Entry**

```typescript
// frontend/src/main.tsx
import React from 'react';
import ReactDOM from 'react-dom/client';
import { App } from './App';
import 'bootstrap/dist/css/bootstrap.min.css';
import './styles/global.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
```

#### Día 5: Testing de Login

```bash
# Probar flujo completo
cd frontend/
npm run dev

# Acceder a http://localhost:3000
# Debería redirigir a /login
# Ingresar credenciales
# Debería redirigir a /dashboard (aún vacío)
```

---

### SEMANA 3-4: Dashboard Windows-like UI

#### Arquitectura del Dashboard

```
DashboardPage
├── Shell (Layout global)
│   ├── Header
│   │   ├── Logo
│   │   ├── SearchBar
│   │   ├── NotificationBell
│   │   └── ProfileMenu
│   │
│   └── Main Content
│       ├── DesktopGrid
│       │   ├── AppIcon (AgendaTec)
│       │   ├── AppIcon (Helpdesk)
│       │   ├── AppIcon (Config)
│       │   └── AppIcon (Trash)
│       │
│       ├── WindowManager
│       │   ├── Window (componente reutilizable)
│       │   │   ├── Titlebar
│       │   │   ├── Iframe (carga app Jinja2)
│       │   │   └── ResizeHandles
│       │   └── ...más windows
│       │
│       └── Taskbar
│           ├── StartButton
│           ├── SearchInput
│           ├── PinnedApps
│           ├── OpenApps
│           └── SystemTray
│               ├── NotificationIcon
│               ├── DateTime
│               └── UserAvatar
```

#### Día 1-2: Window Store + Types

**1. Window Types**

```typescript
// frontend/src/features/dashboard/types/window.types.ts
export interface AppConfig {
  id: string;
  name: string;
  icon: string;
  iframeSrc: string;
  color?: string;
}

export interface WindowState {
  id: string;
  appId: string;
  appName: string;
  iframeSrc: string;
  icon: string;
  isMinimized: boolean;
  isMaximized: boolean;
  isFocused: boolean;
  position: { x: number; y: number };
  size: { width: number; height: number };
  zIndex: number;
}

export const APP_CONFIGS: Record<string, AppConfig> = {
  helpdesk: {
    id: 'helpdesk',
    name: 'Help Desk',
    icon: 'ticket',
    iframeSrc: '/help-desk/',
    color: '#0d6efd',
  },
  agendatec: {
    id: 'agendatec',
    name: 'AgendaTec',
    icon: 'calendar',
    iframeSrc: '/agendatec/',
    color: '#198754',
  },
  config: {
    id: 'config',
    name: 'Configuración',
    icon: 'settings',
    iframeSrc: '/itcj/config',
    color: '#6c757d',
  },
};
```

**2. Window Store**

```typescript
// frontend/src/features/dashboard/store/windowStore.ts
import { create } from 'zustand';
import { WindowState, APP_CONFIGS } from '../types/window.types';

interface WindowStore {
  windows: WindowState[];
  nextZIndex: number;

  openWindow: (appId: string) => void;
  closeWindow: (windowId: string) => void;
  focusWindow: (windowId: string) => void;
  minimizeWindow: (windowId: string) => void;
  maximizeWindow: (windowId: string) => void;
  updateWindowPosition: (windowId: string, x: number, y: number) => void;
  updateWindowSize: (windowId: string, width: number, height: number) => void;
}

export const useWindowStore = create<WindowStore>((set, get) => ({
  windows: [],
  nextZIndex: 100,

  openWindow: (appId) => {
    const config = APP_CONFIGS[appId];
    if (!config) return;

    // Verificar si ya está abierto
    const existing = get().windows.find((w) => w.appId === appId);
    if (existing) {
      // Solo focus
      get().focusWindow(existing.id);
      return;
    }

    const newWindow: WindowState = {
      id: `window-${Date.now()}`,
      appId: config.id,
      appName: config.name,
      iframeSrc: config.iframeSrc,
      icon: config.icon,
      isMinimized: false,
      isMaximized: false,
      isFocused: true,
      position: { x: 100 + get().windows.length * 20, y: 100 + get().windows.length * 20 },
      size: { width: 1000, height: 600 },
      zIndex: get().nextZIndex,
    };

    set((state) => ({
      windows: state.windows.map((w) => ({ ...w, isFocused: false })).concat(newWindow),
      nextZIndex: state.nextZIndex + 1,
    }));
  },

  closeWindow: (windowId) => {
    set((state) => ({
      windows: state.windows.filter((w) => w.id !== windowId),
    }));
  },

  focusWindow: (windowId) => {
    set((state) => ({
      windows: state.windows.map((w) =>
        w.id === windowId
          ? { ...w, isFocused: true, isMinimized: false, zIndex: state.nextZIndex }
          : { ...w, isFocused: false }
      ),
      nextZIndex: state.nextZIndex + 1,
    }));
  },

  minimizeWindow: (windowId) => {
    set((state) => ({
      windows: state.windows.map((w) =>
        w.id === windowId ? { ...w, isMinimized: true, isFocused: false } : w
      ),
    }));
  },

  maximizeWindow: (windowId) => {
    set((state) => ({
      windows: state.windows.map((w) =>
        w.id === windowId ? { ...w, isMaximized: !w.isMaximized, isFocused: true } : w
      ),
    }));
  },

  updateWindowPosition: (windowId, x, y) => {
    set((state) => ({
      windows: state.windows.map((w) => (w.id === windowId ? { ...w, position: { x, y } } : w)),
    }));
  },

  updateWindowSize: (windowId, width, height) => {
    set((state) => ({
      windows: state.windows.map((w) =>
        w.id === windowId ? { ...w, size: { width, height } } : w
      ),
    }));
  },
}));
```

#### Día 3-4: Window Components

**1. Window Component**

```typescript
// frontend/src/features/dashboard/components/Window.tsx
import { useRef, useEffect } from 'react';
import { Minus, Maximize2, X } from 'lucide-react';
import { WindowState } from '../types/window.types';
import { useWindowStore } from '../store/windowStore';

interface WindowProps {
  window: WindowState;
}

export const Window = ({ window }: WindowProps) => {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const { closeWindow, focusWindow, minimizeWindow, maximizeWindow } = useWindowStore();

  useEffect(() => {
    // PostMessage listener para comunicación con iframe
    const handleMessage = (event: MessageEvent) => {
      if (event.origin !== window.origin) return;

      // Manejar mensajes del iframe (apps Jinja2)
      switch (event.data.type) {
        case 'LOGOUT':
          // Manejar logout desde app
          break;
        case 'NAVIGATE':
          // Actualizar URL del iframe
          break;
      }
    };

    window.addEventListener('message', handleMessage);
    return () => window.removeEventListener('message', handleMessage);
  }, []);

  if (window.isMinimized) return null;

  const style = window.isMaximized
    ? {
        position: 'fixed' as const,
        top: 0,
        left: 0,
        width: '100vw',
        height: 'calc(100vh - 48px)', // Dejar espacio para taskbar
        zIndex: window.zIndex,
      }
    : {
        position: 'absolute' as const,
        top: window.position.y,
        left: window.position.x,
        width: window.size.width,
        height: window.size.height,
        zIndex: window.zIndex,
      };

  return (
    <div
      className={`app-window ${window.isFocused ? 'focused' : ''}`}
      style={style}
      onClick={() => focusWindow(window.id)}
    >
      {/* Titlebar */}
      <div className="window-titlebar">
        <div className="window-title">
          <span className="window-icon">
            <i className={`bi bi-${window.icon}`} />
          </span>
          <span>{window.appName}</span>
        </div>
        <div className="window-controls">
          <button
            className="window-control-btn"
            onClick={(e) => {
              e.stopPropagation();
              minimizeWindow(window.id);
            }}
          >
            <Minus size={16} />
          </button>
          <button
            className="window-control-btn"
            onClick={(e) => {
              e.stopPropagation();
              maximizeWindow(window.id);
            }}
          >
            <Maximize2 size={16} />
          </button>
          <button
            className="window-control-btn window-close-btn"
            onClick={(e) => {
              e.stopPropagation();
              closeWindow(window.id);
            }}
          >
            <X size={16} />
          </button>
        </div>
      </div>

      {/* Iframe Content */}
      <div className="window-body">
        <iframe
          ref={iframeRef}
          src={window.iframeSrc}
          title={window.appName}
          className="window-iframe"
          sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-downloads"
        />
      </div>
    </div>
  );
};
```

**2. WindowManager Component**

```typescript
// frontend/src/features/dashboard/components/WindowManager.tsx
import { useWindowStore } from '../store/windowStore';
import { Window } from './Window';

export const WindowManager = () => {
  const windows = useWindowStore((state) => state.windows);

  return (
    <div className="windows-container">
      {windows.map((window) => (
        <Window key={window.id} window={window} />
      ))}
    </div>
  );
};
```

**3. DesktopGrid Component**

```typescript
// frontend/src/features/dashboard/components/DesktopGrid.tsx
import { Calendar, Ticket, Settings, Trash2 } from 'lucide-react';
import { useWindowStore } from '../store/windowStore';
import { APP_CONFIGS } from '../types/window.types';

const DESKTOP_APPS = [
  { ...APP_CONFIGS.agendatec, Icon: Calendar },
  { ...APP_CONFIGS.helpdesk, Icon: Ticket },
  { ...APP_CONFIGS.config, Icon: Settings },
  { id: 'trash', name: 'Papelera', Icon: Trash2, color: '#6c757d' },
];

export const DesktopGrid = () => {
  const openWindow = useWindowStore((state) => state.openWindow);

  return (
    <div className="desktop-grid">
      {DESKTOP_APPS.map((app) => (
        <div
          key={app.id}
          className="desktop-icon"
          onDoubleClick={() => {
            if (app.id !== 'trash') {
              openWindow(app.id);
            }
          }}
        >
          <div
            className="icon-wrapper"
            style={{ backgroundColor: app.color || '#0d6efd' }}
          >
            <app.Icon size={32} color="white" />
          </div>
          <span className="icon-label">{app.name}</span>
        </div>
      ))}
    </div>
  );
};
```

**4. Taskbar Component**

```typescript
// frontend/src/features/dashboard/components/Taskbar.tsx
import { Search, Bell, User } from 'lucide-react';
import { useWindowStore } from '../store/windowStore';

export const Taskbar = () => {
  const windows = useWindowStore((state) => state.windows);
  const focusWindow = useWindowStore((state) => state.focusWindow);
  const minimizeWindow = useWindowStore((state) => state.minimizeWindow);

  return (
    <div className="taskbar">
      <div className="taskbar-start">
        <button className="start-button">
          <span>Inicio</span>
        </button>
        <div className="search-bar">
          <Search size={16} />
          <input type="text" placeholder="Buscar..." />
        </div>
      </div>

      <div className="taskbar-apps">
        {windows.map((window) => (
          <button
            key={window.id}
            className={`taskbar-app-btn ${window.isFocused ? 'active' : ''}`}
            onClick={() => {
              if (window.isMinimized) {
                focusWindow(window.id);
              } else if (window.isFocused) {
                minimizeWindow(window.id);
              } else {
                focusWindow(window.id);
              }
            }}
          >
            <i className={`bi bi-${window.icon}`} />
            <span>{window.appName}</span>
          </button>
        ))}
      </div>

      <div className="taskbar-tray">
        <button className="tray-btn">
          <Bell size={18} />
        </button>
        <div className="taskbar-datetime">
          <span className="time">12:30 PM</span>
          <span className="date">15/12/2025</span>
        </div>
        <button className="tray-btn">
          <User size={18} />
        </button>
      </div>
    </div>
  );
};
```

#### Día 5: Dashboard Page + Styles

**1. Dashboard Page**

```typescript
// frontend/src/features/dashboard/pages/DashboardPage.tsx
import { DesktopGrid } from '../components/DesktopGrid';
import { WindowManager } from '../components/WindowManager';
import { Taskbar } from '../components/Taskbar';
import './dashboard.css';

export const DashboardPage = () => {
  return (
    <div className="dashboard-container">
      <DesktopGrid />
      <WindowManager />
      <Taskbar />
    </div>
  );
};
```

**2. Dashboard Styles**

```css
/* frontend/src/features/dashboard/pages/dashboard.css */
.dashboard-container {
  position: fixed;
  top: 0;
  left: 0;
  width: 100vw;
  height: 100vh;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  overflow: hidden;
}

.desktop-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, 100px);
  grid-gap: 20px;
  padding: 20px;
  height: calc(100vh - 48px);
}

.desktop-icon {
  display: flex;
  flex-direction: column;
  align-items: center;
  cursor: pointer;
  transition: transform 0.2s;
}

.desktop-icon:hover {
  transform: scale(1.05);
}

.icon-wrapper {
  width: 64px;
  height: 64px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 12px;
  margin-bottom: 8px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
}

.icon-label {
  color: white;
  font-size: 12px;
  text-align: center;
  text-shadow: 0 2px 4px rgba(0, 0, 0, 0.3);
}

/* Windows */
.windows-container {
  position: relative;
  width: 100%;
  height: calc(100vh - 48px);
}

.app-window {
  background: white;
  border-radius: 8px 8px 0 0;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.app-window.focused {
  box-shadow: 0 12px 48px rgba(0, 0, 0, 0.4);
}

.window-titlebar {
  height: 40px;
  background: #f8f9fa;
  border-bottom: 1px solid #dee2e6;
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0 12px;
  cursor: move;
}

.window-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 500;
}

.window-controls {
  display: flex;
  gap: 4px;
}

.window-control-btn {
  width: 32px;
  height: 32px;
  border: none;
  background: transparent;
  border-radius: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: background 0.2s;
}

.window-control-btn:hover {
  background: #e9ecef;
}

.window-close-btn:hover {
  background: #dc3545;
  color: white;
}

.window-body {
  flex: 1;
  overflow: hidden;
}

.window-iframe {
  width: 100%;
  height: 100%;
  border: none;
}

/* Taskbar */
.taskbar {
  position: fixed;
  bottom: 0;
  left: 0;
  width: 100%;
  height: 48px;
  background: rgba(255, 255, 255, 0.9);
  backdrop-filter: blur(20px);
  border-top: 1px solid rgba(0, 0, 0, 0.1);
  display: flex;
  align-items: center;
  padding: 0 12px;
  gap: 12px;
  z-index: 9999;
}

.taskbar-start {
  display: flex;
  gap: 8px;
}

.start-button {
  height: 36px;
  padding: 0 16px;
  border: none;
  background: #0d6efd;
  color: white;
  border-radius: 6px;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.2s;
}

.start-button:hover {
  background: #0b5ed7;
}

.search-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  background: white;
  border: 1px solid #dee2e6;
  border-radius: 6px;
  padding: 0 12px;
  height: 36px;
}

.search-bar input {
  border: none;
  outline: none;
  width: 200px;
}

.taskbar-apps {
  flex: 1;
  display: flex;
  gap: 4px;
  overflow-x: auto;
}

.taskbar-app-btn {
  display: flex;
  align-items: center;
  gap: 8px;
  height: 36px;
  padding: 0 12px;
  border: none;
  background: white;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s;
}

.taskbar-app-btn:hover {
  background: #f8f9fa;
}

.taskbar-app-btn.active {
  background: #e9ecef;
  border-bottom: 2px solid #0d6efd;
}

.taskbar-tray {
  display: flex;
  align-items: center;
  gap: 8px;
}

.tray-btn {
  width: 36px;
  height: 36px;
  border: none;
  background: transparent;
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: background 0.2s;
}

.tray-btn:hover {
  background: #f8f9fa;
}

.taskbar-datetime {
  display: flex;
  flex-direction: column;
  font-size: 11px;
  line-height: 1.2;
  text-align: right;
}
```

---

### SEMANA 5: Notificaciones + Profile

**Contenido:** Implementar SSE client en React, notification bell, profile menu.

**Por brevedad, omito detalles completos aquí. El patrón es similar:**
1. Hook `useSSE` para EventSource
2. Notification store (Zustand)
3. Notification bell component
4. Profile menu dropdown

---

### SEMANA 6: Config Pages

**Contenido:** Migrar páginas de configuración (Users, Roles, Departments, Permissions).

**Patrón:**
1. API hooks (useUsers, useRoles, etc.)
2. Table components (reusable DataTable)
3. Form modals (create/edit)
4. Delete confirmations

---

## TESTING Y QA

### Testing Manual

**Checklist de funcionalidad:**
- [ ] Login con credenciales correctas
- [ ] Login con credenciales incorrectas (error)
- [ ] Logout funcionando
- [ ] Dashboard carga
- [ ] Doble-click en ícono abre app en iframe
- [ ] Iframe carga app Jinja2 correctamente
- [ ] Multiple windows abiertas
- [ ] Minimize/Maximize/Close window
- [ ] Taskbar muestra apps abiertas
- [ ] Focus entre windows
- [ ] Notificaciones en tiempo real (SSE)
- [ ] Profile menu
- [ ] Config pages CRUD operations

### Testing Automatizado

```bash
# Unit tests
npm run test

# E2E tests (Playwright)
npm run test:e2e
```

---

## DEPLOYMENT

### Producción

**Docker Compose (Producción):**

```yaml
# docker-compose.yml
version: '3.8'

services:
  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile.prod
    image: itcj-frontend:latest
    container_name: itcj-frontend
    # No exponemos puerto, Nginx maneja esto

  backend:
    build:
      context: .
      dockerfile: Dockerfile
    image: itcj-backend:latest
    container_name: itcj-backend
    environment:
      - FLASK_ENV=production
      - DATABASE_URL=${DATABASE_URL}
      - REDIS_URL=${REDIS_URL}
      - SECRET_KEY=${SECRET_KEY}
    depends_on:
      - postgres
      - redis

  nginx:
    image: nginx:alpine
    container_name: itcj-nginx
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./docker/nginx.conf:/etc/nginx/nginx.conf:ro
      - ./frontend/dist:/usr/share/nginx/html:ro
    depends_on:
      - backend
      - frontend
```

**Dockerfile Frontend:**

```dockerfile
# frontend/Dockerfile.prod
FROM node:20-alpine AS build

WORKDIR /app

COPY package*.json ./
RUN npm ci --only=production

COPY . .
RUN npm run build

# Nginx para servir
FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
```

**Nginx Config:**

```nginx
# docker/nginx.conf
server {
    listen 80;
    server_name itcj.cdjuarez.tecnm.mx;

    # React SPA
    location / {
        root /usr/share/nginx/html;
        try_files $uri $uri/ /index.html;
    }

    # API Backend
    location /api/ {
        proxy_pass http://backend:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # Apps (iframes)
    location /help-desk/ {
        proxy_pass http://backend:8000;
    }

    location /agendatec/ {
        proxy_pass http://backend:8000;
    }

    # SSE
    location /api/core/v1/notifications/stream {
        proxy_pass http://backend:8000;
        proxy_set_header Connection '';
        proxy_http_version 1.1;
        chunked_transfer_encoding off;
        proxy_buffering off;
        proxy_cache off;
    }
}
```

---

## CONCLUSIÓN

Este plan proporciona una **ruta clara y detallada** para migrar el Core a React manteniendo las apps en Jinja2. El patrón de iframe ya existente hace que esta migración sea **de bajo riesgo** y permite **iteraciones incrementales**.

**Próximos pasos:**
1. ✅ Ejecutar PASO 0 (Setup)
2. ✅ Implementar SEMANA 1 (Infraestructura)
3. ✅ Implementar SEMANA 2 (Login)
4. ✅ Implementar SEMANA 3-4 (Dashboard)
5. ✅ Continuar con notificaciones, profile, config

**Timeline total:** 6-8 semanas para Core completo + 2-4 semanas buffer = **2-3 meses**

---

**Última actualización:** 2025-12-16
**Autor:** Plan de migración ITCJ Core → React
**Versión documento:** 1.0
