import { AppRoutes } from './routes';

/**
 * App - Componente raíz de la aplicación
 *
 * Simplemente renderiza el sistema de rutas.
 * La autenticación se maneja en ProtectedRoute.
 */
function App() {
  return <AppRoutes />;
}

export default App;
