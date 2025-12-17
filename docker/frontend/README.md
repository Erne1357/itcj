# Docker Frontend Configuration

Este directorio contiene los Dockerfiles para el frontend React del proyecto ITCJ.

## Archivos

### Dockerfile.dev
Imagen para desarrollo con hot reload:
- Node.js 20 Alpine
- Puerto 5173 (Vite dev server)
- Volumen montado para hot reload
- Auto-instala dependencias al iniciar

**Uso:**
```bash
docker-compose -f docker/compose/docker-compose.dev.yml up frontend
```

### Dockerfile.prod
Build multi-stage para producci贸n:
- Stage 1: Build de la aplicaci贸n React con Vite
- Stage 2: Servir con Nginx Alpine
- Optimizado para tama帽o m铆nimo
- Configurado para SPA (Single Page Application)

**Uso:**
```bash
docker-compose -f docker/compose/docker-compose.prod.yml build frontend
docker-compose -f docker/compose/docker-compose.prod.yml up frontend
```

## Puertos

- **Desarrollo**: 5173 (Vite dev server)
- **Producci贸n**: 80 (Nginx)

## Arquitectura

```
Cliente
   鈫?
Nginx (Puerto 8080)
   鈫?鈹鈹?鈹? / (React SPA)        鈫? Frontend (5173 dev / 80 prod)
   鈫?鈹?
   鈫?鈹鈹?鈹? /api/*             鈫? Backend (8000)
   鈫?鈹?
   鈫?鈹鈹?鈹? /help-desk/*       鈫? Backend (Jinja2 para iframes)
   鈫?鈹?
   鈫?鈹?鈹? /agendatec/*       鈫? Backend (Jinja2 para iframes)
```

## Notas

- El frontend en desarrollo tiene hot reload habilitado
- Nginx maneja el routing de SPA en producci贸n
- Las apps legacy (Helpdesk, AgendaTec) se cargan en iframes desde el backend
