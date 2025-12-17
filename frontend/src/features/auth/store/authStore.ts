import { create } from 'zustand';
import { devtools, persist } from 'zustand/middleware';
import type { User } from '../types/auth.types';

/**
 * Estado de autenticación
 */
interface AuthState {
  user: User | null;
  isAuthenticated: boolean;
  isLoading: boolean;
}

/**
 * Acciones de autenticación
 */
interface AuthActions {
  setUser: (user: User | null) => void;
  setLoading: (isLoading: boolean) => void;
  logout: () => void;
  reset: () => void;
}

/**
 * Estado inicial
 */
const initialState: AuthState = {
  user: null,
  isAuthenticated: false,
  isLoading: true, // true por defecto para verificar sesión al cargar
};

/**
 * Store de autenticación usando Zustand
 *
 * Este store maneja el estado global de autenticación.
 * Persiste el usuario en localStorage para mantener la sesión entre recargas.
 */
export const useAuthStore = create<AuthState & AuthActions>()(
  devtools(
    persist(
      (set) => ({
        // Estado inicial
        ...initialState,

        // Acciones
        setUser: (user) =>
          set(
            {
              user,
              isAuthenticated: !!user,
              isLoading: false,
            },
            false,
            'auth/setUser'
          ),

        setLoading: (isLoading) =>
          set(
            {
              isLoading,
            },
            false,
            'auth/setLoading'
          ),

        logout: () =>
          set(
            {
              user: null,
              isAuthenticated: false,
              isLoading: false,
            },
            false,
            'auth/logout'
          ),

        reset: () =>
          set(
            {
              ...initialState,
              isLoading: false, // No queremos loading después de reset
            },
            false,
            'auth/reset'
          ),
      }),
      {
        name: 'auth-storage', // nombre en localStorage
        partialize: (state) => ({
          // Solo persistimos el usuario, no el loading
          user: state.user,
          isAuthenticated: state.isAuthenticated,
        }),
      }
    ),
    {
      name: 'AuthStore', // nombre para Redux DevTools
      enabled: import.meta.env.DEV, // solo en desarrollo
    }
  )
);

/**
 * Selectores útiles para evitar re-renders innecesarios
 */
export const selectUser = (state: AuthState & AuthActions) => state.user;
export const selectIsAuthenticated = (state: AuthState & AuthActions) => state.isAuthenticated;
export const selectIsLoading = (state: AuthState & AuthActions) => state.isLoading;
