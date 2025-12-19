import { useState, useEffect, useRef } from 'react';
import { X, Minus, Maximize2, Minimize2 } from 'lucide-react';

export interface WindowProps {
  id: string;
  title: string;
  url: string;
  icon?: string;
  onClose: () => void;
  onMinimize: () => void;
  isMinimized?: boolean;
  zIndex?: number;
  onFocus?: () => void;
}

interface Position {
  x: number;
  y: number;
}

/**
 * Window - Ventana de aplicación estilo Windows
 *
 * Características:
 * - Iframe para aplicaciones legacy
 * - Minimizar, Maximizar, Cerrar
 * - Título dinámico basado en la URL del iframe
 * - Siempre inicia maximizada
 * - Draggable (cuando no está maximizada)
 */
export function Window({
  title: initialTitle,
  url,
  icon,
  onClose,
  onMinimize,
  isMinimized = false,
  zIndex = 1000,
  onFocus,
}: WindowProps) {
  const [isMaximized, setIsMaximized] = useState(true); // Siempre empieza maximizada
  const [title] = useState(initialTitle);
  const [currentUrl, setCurrentUrl] = useState(url);
  const [position, setPosition] = useState<Position>({ x: 100, y: 100 });
  const [isDragging, setIsDragging] = useState(false);
  const [dragStart, setDragStart] = useState<Position>({ x: 0, y: 0 });
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const windowRef = useRef<HTMLDivElement>(null);

  // Detectar cambios de URL en el iframe
  useEffect(() => {
    const iframe = iframeRef.current;
    if (!iframe) return;

    const updateUrlFromIframe = () => {
      try {
        // Intentar obtener la URL del iframe (puede fallar por CORS)
        const iframeUrl = iframe.contentWindow?.location.pathname || url;
        setCurrentUrl(iframeUrl);
      } catch (e) {
        // CORS error - usar la URL inicial
        setCurrentUrl(url);
      }
    };

    // Escuchar cambios en el iframe
    iframe.addEventListener('load', updateUrlFromIframe);

    return () => {
      iframe.removeEventListener('load', updateUrlFromIframe);
    };
  }, [url]);

  // Drag and drop handlers
  const handleMouseDown = (e: React.MouseEvent) => {
    if (isMaximized) return; // No drag si está maximizada
    if (onFocus) onFocus();

    setIsDragging(true);
    setDragStart({
      x: e.clientX - position.x,
      y: e.clientY - position.y,
    });
  };

  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (!isDragging || isMaximized) return;

      const newX = e.clientX - dragStart.x;
      const newY = e.clientY - dragStart.y;

      // Límites para que no se salga de la pantalla
      const maxX = window.innerWidth - 300; // Ancho mínimo visible
      const maxY = window.innerHeight - 100; // Alto mínimo visible

      setPosition({
        x: Math.max(0, Math.min(newX, maxX)),
        y: Math.max(0, Math.min(newY, maxY)),
      });
    };

    const handleMouseUp = () => {
      setIsDragging(false);
    };

    if (isDragging) {
      document.addEventListener('mousemove', handleMouseMove);
      document.addEventListener('mouseup', handleMouseUp);
    }

    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
    };
  }, [isDragging, dragStart, isMaximized]);

  const handleMaximize = () => {
    setIsMaximized(!isMaximized);
  };

  const handleClick = () => {
    if (onFocus) {
      onFocus();
    }
  };

  if (isMinimized) {
    return null; // No renderizar si está minimizada (pero sigue en el estado)
  }

  return (
    <div
      ref={windowRef}
      className={`app-window ${isMaximized ? 'maximized' : ''}`}
      style={{
        zIndex,
        ...(isMaximized
          ? {}
          : {
              top: `${position.y}px`,
              left: `${position.x}px`,
              width: '80%',
              height: '80%',
            }),
      }}
      onClick={handleClick}
    >
      {/* Titlebar */}
      <div className="window-titlebar" onMouseDown={handleMouseDown}>
        <div className="window-title">
          {icon && <img src={icon} alt="" style={{ width: '16px', height: '16px' }} />}
          <div>
            <div className="window-title-text">{title}</div>
            <div className="window-url">{currentUrl}</div>
          </div>
        </div>

        <div className="window-controls">
          {/* Minimize */}
          <button
            className="window-control"
            onClick={onMinimize}
            title="Minimizar"
            aria-label="Minimizar"
          >
            <Minus size={14} />
          </button>

          {/* Maximize/Restore */}
          <button
            className="window-control"
            onClick={handleMaximize}
            title={isMaximized ? 'Restaurar' : 'Maximizar'}
            aria-label={isMaximized ? 'Restaurar' : 'Maximizar'}
          >
            {isMaximized ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
          </button>

          {/* Close */}
          <button
            className="window-control close"
            onClick={onClose}
            title="Cerrar"
            aria-label="Cerrar"
          >
            <X size={14} />
          </button>
        </div>
      </div>

      {/* Content - Iframe */}
      <div className="window-content">
        <iframe
          ref={iframeRef}
          src={url}
          className="window-iframe"
          title={title}
          sandbox="allow-same-origin allow-scripts allow-forms allow-popups allow-modals"
        />
      </div>
    </div>
  );
}
