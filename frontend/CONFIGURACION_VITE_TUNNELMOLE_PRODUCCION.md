# Configuración de Vite para Tunnelmole y Producción

## 🚀 Uso Inmediato - Tunnelmole (Desarrollo Móvil)

### Paso 1: Actualizar URL de Tunnelmole
Cada vez que inicies tunnelmole, obtendrás una URL diferente. Actualiza el archivo `vite.config.tunnelmole.ts`:

```typescript
hmr: {
  clientPort: 443,
  host: 'tu-nueva-url.tunnelmole.net', // ⚠️ Actualizar con tu URL actual
},
```

### Paso 2: Ejecutar servidor con configuración tunnelmole
```bash
# En lugar de npm run dev, usa:
npm run dev:tunnel
```

### Paso 3: Iniciar tunnelmole
```bash
# En otra terminal
tunnelmole 5173
```

### Paso 4: Acceder desde tu celular
Usa la URL que te proporcionó tunnelmole en tu celular:
```
https://pclf9l-ip-201-174-23-164.tunnelmole.net
```

---

## 🏭 Configuración para Producción

### Dominio Final: `enlinea.cdjuarez.tecnm.mx`

### 1. Build para producción
```bash
cd frontend
npm run build -- --config vite.config.prod.ts
```

### 2. Configuración de Nginx

El archivo `nginx.prod.conf` ya está configurado correctamente. Necesitas asegurarte de:

#### a) Agregar configuración HTTPS en nginx.prod.conf:

```nginx
server {
    listen 443 ssl http2;
    server_name enlinea.cdjuarez.tecnm.mx;

    # Certificados SSL (Let's Encrypt)
    ssl_certificate /etc/nginx/ssl/fullchain.pem;
    ssl_certificate_key /etc/nginx/ssl/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    # Resto de configuración...
    client_max_body_size 10M;
    
    # Tu configuración actual de locations
}

# Redirección HTTP a HTTPS
server {
    listen 80;
    server_name enlinea.cdjuarez.tecnm.mx;
    return 301 https://$server_name$request_uri;
}
```

#### b) Variables de entorno para frontend en producción

Crea `.env.production` en el directorio frontend:

```env
VITE_API_URL=https://enlinea.cdjuarez.tecnm.mx/api
VITE_WS_URL=wss://enlinea.cdjuarez.tecnm.mx
```

#### c) Actualizar docker-compose.prod.yml

Asegúrate de que el servicio nginx tenga el nombre del servidor correcto:

```yaml
services:
  nginx:
    environment:
      - SERVER_NAME=enlinea.cdjuarez.tecnm.mx
```

### 3. DNS Configuration

Configura el registro DNS en tu proveedor:

```
Tipo: A
Nombre: enlinea.cdjuarez.tecnm.mx
Valor: [IP del servidor de producción]
TTL: 3600
```

### 4. SSL/TLS Certificates

Usa Certbot para obtener certificados SSL gratuitos:

```bash
# En el servidor de producción
docker run -it --rm \
  -v /etc/letsencrypt:/etc/letsencrypt \
  certbot/certbot certonly \
  --standalone \
  -d enlinea.cdjuarez.tecnm.mx
```

### 5. Deploy Final

```bash
# Build frontend con configuración de producción
cd frontend
npm run build -- --config vite.config.prod.ts

# Levantar servicios
docker compose -f docker/compose/docker-compose.prod.yml up -d --build
```

---

## 📝 Resumen de Archivos Creados

1. **`vite.config.tunnelmole.ts`** - Configuración para desarrollo con tunnelmole
2. **`vite.config.prod.ts`** - Configuración optimizada para producción
3. **Script `dev:tunnel`** - Agregado a package.json para usar tunnelmole

## 🔧 Comandos Útiles

```bash
# Desarrollo normal
npm run dev

# Desarrollo con tunnelmole (celular)
npm run dev:tunnel

# Build para producción
npm run build -- --config vite.config.prod.ts

# Preview de build de producción
npm run preview
```

## ⚠️ Notas Importantes

1. **Tunnelmole**: La URL cambia cada vez que lo ejecutas, actualiza `vite.config.tunnelmole.ts`
2. **Producción**: No uses `server.hmr` en producción, nginx manejará las conexiones
3. **CORS**: En producción, asegúrate de que el backend permita el dominio `enlinea.cdjuarez.tecnm.mx`
4. **Certificados**: Renueva los certificados SSL cada 90 días (Certbot puede hacerlo automáticamente)

## 🐛 Troubleshooting

### Problema: "Invalid Host header" en tunnelmole
**Solución**: Asegúrate de que `server.hmr.host` en `vite.config.tunnelmole.ts` coincida con tu URL de tunnelmole

### Problema: WebSocket no conecta en producción
**Solución**: Verifica que nginx tenga configurado el proxy para `/socket.io/` con headers de upgrade

### Problema: Archivos estáticos no cargan
**Solución**: Verifica la configuración `base` en vite.config y las rutas en nginx
