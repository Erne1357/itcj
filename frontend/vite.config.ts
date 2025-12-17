import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],

  // Path aliases para imports limpios
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },

  // Configuración del servidor de desarrollo
  server: {
    port: 5173,
    host: true, // Necesario para Docker
    strictPort: true,

    // Proxy para llamadas API al backend Flask
    proxy: {
      // Proxy para APIs
      '/api': {
        target: 'http://localhost:8080',
        changeOrigin: true,
        secure: false,
      },
      // Proxy para apps legacy (Jinja2) - para desarrollo fuera de Docker
      '/help-desk': {
        target: 'http://localhost:8080',
        changeOrigin: true,
        secure: false,
      },
      '/agendatec': {
        target: 'http://localhost:8080',
        changeOrigin: true,
        secure: false,
      },
      // Proxy para archivos estáticos del backend
      '/static': {
        target: 'http://localhost:8080',
        changeOrigin: true,
        secure: false,
      },
    },
  },

  // Configuración de build para producción
  build: {
    outDir: 'dist',
    sourcemap: true,
    // Optimizaciones de chunk
    rollupOptions: {
      output: {
        manualChunks: {
          'react-vendor': ['react', 'react-dom'],
        },
      },
    },
  },
})
