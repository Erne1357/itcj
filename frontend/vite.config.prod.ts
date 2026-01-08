import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

// Configuración para producción
// Dominio: enlinea.cdjuarez.tecnm.mx
export default defineConfig({
  plugins: [react()],

  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },

  // En producción, nginx/servidor web manejará esto
  // No necesitas configurar server.hmr aquí
  build: {
    outDir: 'dist',
    sourcemap: false, // Desactivar en producción por seguridad y tamaño
    rollupOptions: {
      output: {
        manualChunks: {
          'react-vendor': ['react', 'react-dom'],
          'router': ['react-router-dom'],
          'form': ['react-hook-form', '@hookform/resolvers'],
          'ui': ['react-bootstrap', 'bootstrap'],
        },
      },
    },
    // Optimizaciones adicionales
    minify: 'terser',
    terserOptions: {
      compress: {
        drop_console: true, // Eliminar console.log en producción
      },
    },
  },

  // Base URL para producción
  base: '/',
})
