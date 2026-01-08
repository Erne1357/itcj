import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

// Configuración para desarrollo con tunnelmole
// Uso: npm run dev:tunnel
export default defineConfig({
  plugins: [react()],

  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },

  server: {
    port: 5173,
    host: true,
    strictPort: true,

    // Configuración HMR para tunnelmole
    hmr: {
      clientPort: 443, // Puerto HTTPS de tunnelmole
      // Actualiza este host con tu URL de tunnelmole actual
      host: 'pclf9l-ip-201-174-23-164.tunnelmole.net',
    },

    proxy: {
      '/api': {
        target: 'http://localhost:8080',
        changeOrigin: true,
        secure: false,
      },
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
      '/static': {
        target: 'http://localhost:8080',
        changeOrigin: true,
        secure: false,
      },
    },
  },

  build: {
    outDir: 'dist',
    sourcemap: true,
    rollupOptions: {
      output: {
        manualChunks: {
          'react-vendor': ['react', 'react-dom'],
        },
      },
    },
  },
})
