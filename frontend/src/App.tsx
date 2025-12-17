import { useState } from 'react';
import reactLogo from './assets/react.svg';
import viteLogo from '/vite.svg';
import './App.css';
import { checkHealth } from './lib/api/health';
import { useAuth, useLogin, useLogout } from './features/auth/hooks';

function App() {
  const [count, setCount] = useState(0);
  const [apiStatus, setApiStatus] = useState<string>('No verificado');
  const [isLoadingHealth, setIsLoadingHealth] = useState(false);

  // Auth hooks
  const { user, isAuthenticated, isLoading: isAuthLoading } = useAuth();
  const { login, isLoading: isLoginLoading, isError: isLoginError, error: loginError } = useLogin();
  const { logout: handleLogout, isLoading: isLogoutLoading } = useLogout();

  // Estados para el formulario de login
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');

  const handleCheckAPI = async () => {
    setIsLoadingHealth(true);
    setApiStatus('Verificando...');

    try {
      const response = await checkHealth();
      setApiStatus(`✅ ${response.status}: ${response.message}`);
    } catch (error: any) {
      setApiStatus(
        `❌ Error: ${error.response?.data?.message || error.message || 'No se pudo conectar al backend'}`
      );
    } finally {
      setIsLoadingHealth(false);
    }
  };

  const handleLogin = (e: React.FormEvent) => {
    e.preventDefault();
    login({ username, password });
  };

  return (
    <>
      <div>
        <a href="https://vite.dev" target="_blank">
          <img src={viteLogo} className="logo" alt="Vite logo" />
        </a>
        <a href="https://react.dev" target="_blank">
          <img src={reactLogo} className="logo react" alt="React logo" />
        </a>
      </div>
      <h1>ITCJ Frontend - React + TypeScript</h1>

      <div className="card">
        <button onClick={() => setCount((count) => count + 1)}>count is {count}</button>
        <p>
          Edit <code>src/App.tsx</code> and save to test HMR
        </p>
      </div>

      {/* Health Check */}
      <div className="card">
        <h2>🔗 Test de Conectividad Backend</h2>
        <button onClick={handleCheckAPI} disabled={isLoadingHealth}>
          {isLoadingHealth ? 'Verificando...' : 'Verificar Conexión API'}
        </button>
        <p style={{ marginTop: '1rem', fontSize: '0.9rem' }}>
          <strong>Estado:</strong> {apiStatus}
        </p>
        <p style={{ fontSize: '0.8rem', color: '#888' }}>
          Endpoint: {import.meta.env.VITE_API_BASE_URL}/core/v1/health
        </p>
      </div>

      {/* Auth Test */}
      <div className="card">
        <h2>🔐 Test de Autenticación</h2>

        {isAuthLoading ? (
          <p>Verificando sesión...</p>
        ) : isAuthenticated && user ? (
          <div>
            <p style={{ color: '#4caf50' }}>
              <strong>✅ Usuario autenticado</strong>
            </p>
            <div
              style={{
                background: '#f5f5f5',
                padding: '1rem',
                borderRadius: '8px',
                marginTop: '1rem',
                textAlign: 'left',
              }}
            >
              <p>
                <strong>ID:</strong> {user.sub}
              </p>
              <p>
                <strong>Username:</strong> {user.cn}
              </p>
              <p>
                <strong>Nombre:</strong> {user.name}
              </p>
              <p>
                <strong>Roles:</strong> {user.role.join(', ')}
              </p>
            </div>
            <button
              onClick={() => handleLogout()}
              disabled={isLogoutLoading}
              style={{ marginTop: '1rem', background: '#f44336' }}
            >
              {isLogoutLoading ? 'Cerrando sesión...' : 'Cerrar Sesión'}
            </button>
          </div>
        ) : (
          <form onSubmit={handleLogin} style={{ marginTop: '1rem' }}>
            <div style={{ marginBottom: '1rem' }}>
              <input
                type="text"
                placeholder="Username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                style={{
                  padding: '0.5rem',
                  width: '200px',
                  borderRadius: '4px',
                  border: '1px solid #ccc',
                }}
              />
            </div>
            <div style={{ marginBottom: '1rem' }}>
              <input
                type="password"
                placeholder="Password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                style={{
                  padding: '0.5rem',
                  width: '200px',
                  borderRadius: '4px',
                  border: '1px solid #ccc',
                }}
              />
            </div>
            <button type="submit" disabled={isLoginLoading}>
              {isLoginLoading ? 'Iniciando sesión...' : 'Iniciar Sesión'}
            </button>

            {isLoginError && (
              <p style={{ color: '#f44336', marginTop: '1rem' }}>
                ❌ Error: {(loginError as any)?.message || 'Credenciales inválidas'}
              </p>
            )}
          </form>
        )}
      </div>

      <p className="read-the-docs">Click on the Vite and React logos to learn more</p>
    </>
  );
}

export default App;
