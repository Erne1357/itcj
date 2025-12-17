import { QueryClient } from '@tanstack/react-query';

/**
 * Configuración del cliente de React Query
 * Este cliente se usa para manejar el estado de las peticiones API
 */
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1, // Reintentar una vez si falla
      refetchOnWindowFocus: false, // No refrescar al cambiar de pestaña
      staleTime: 5 * 60 * 1000, // Los datos son "frescos" por 5 minutos
      gcTime: 10 * 60 * 1000, // Garbage collection después de 10 minutos
    },
    mutations: {
      retry: 0, // No reintentar mutaciones fallidas
    },
  },
});
