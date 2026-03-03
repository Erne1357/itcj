// iframe-bridge.js - Incluir en todas las páginas que se cargan en iframe
(function() {
  'use strict'
  
  // Solo ejecutar si estamos en un iframe
  if (window.self === window.top) {
    return
  }

  let lastUrl = window.location.href
  let checkInterval

  function notifyParent(type, data = {}) {
    try {
      window.parent.postMessage({
        type: type,
        source: 'iframe-bridge',
        url: window.location.pathname,
        timestamp: Date.now(),
        ...data
      }, window.location.origin)
    } catch (e) {
      console.warn('No se pudo enviar mensaje al parent:', e)
    }
  }

  function checkForLogout() {
    const currentPath = window.location.pathname
    
    // Verificar rutas de logout
    if (currentPath.endsWith('/logout') || 
        currentPath === '/itcj/login' ||
        currentPath.includes('login')) {
      
      notifyParent('LOGOUT', { 
        reason: 'navigation',
        path: currentPath 
      })
      return true
    }
    
    return false
  }

  function checkForLoginForm() {
    // Verificar si estamos en la página de login (formulario presente)
    const loginForm = document.getElementById('loginForm')
    const isLoginPage = loginForm !== null || 
                        document.title.toLowerCase().includes('inicio de sesión') ||
                        document.title.toLowerCase().includes('login')
    
    if (isLoginPage) {
      notifyParent('SESSION_EXPIRED', {
        reason: 'login_page_loaded',
        path: window.location.pathname
      })
      return true
    }
    
    return false
  }

  function checkForSessionExpired() {
    // Verificar si hay indicadores de sesión expirada
    const hasSessionError = document.querySelector('[data-session-expired]') ||
                           document.querySelector('.session-expired') ||
                           window.location.search.includes('session_expired=true')
    
    if (hasSessionError) {
      notifyParent('SESSION_EXPIRED', {
        reason: 'session_expired'
      })
      return true
    }
    
    return false
  }

  function monitorNavigation() {
    const currentUrl = window.location.href
    
    if (currentUrl !== lastUrl) {
      lastUrl = currentUrl
      
      // Notificar cambio de navegación
      notifyParent('NAVIGATION', {
        url: window.location.pathname,
        fullUrl: currentUrl
      })
      
      // Verificar logout o sesión expirada
      if (checkForLogout() || checkForSessionExpired()) {
        if (checkInterval) {
          clearInterval(checkInterval)
        }
        return
      }
    }
  }

  // Monitorear cambios de URL cada 500ms
  checkInterval = setInterval(monitorNavigation, 500)

  // Escuchar cambios en el DOM para detectar logout buttons o mensajes
  const observer = new MutationObserver((mutations) => {
    mutations.forEach((mutation) => {
      // Buscar elementos relacionados con logout
      const logoutElements = document.querySelectorAll('a[href*="logout"], button[data-logout], .logout-btn')
      
      logoutElements.forEach(element => {
        if (!element.dataset.bridgeListener) {
          element.dataset.bridgeListener = 'true'
          element.addEventListener('click', () => {
            // Dar un pequeño delay para que la navegación ocurra
            setTimeout(() => {
              notifyParent('LOGOUT', { 
                reason: 'button_click',
                element: element.outerHTML.substring(0, 100) 
              })
            }, 100)
          })
        }
      })
    })
  })

  // Iniciar observación del DOM
  observer.observe(document.body, {
    childList: true,
    subtree: true
  })

  // Verificación inicial al cargar la página
  window.addEventListener('load', () => {
    // Prioridad: verificar si es página de login primero
    if (checkForLoginForm()) return
    checkForLogout()
    checkForSessionExpired()
  })
  
  // También verificar inmediatamente cuando el DOM está listo
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
      if (checkForLoginForm()) return
      checkForLogout()
      checkForSessionExpired()
    })
  } else {
    // DOM ya está listo, verificar ahora
    setTimeout(() => {
      if (checkForLoginForm()) return
      checkForLogout()
      checkForSessionExpired()
    }, 100)
  }

  // Limpiar al cerrar
  window.addEventListener('beforeunload', () => {
    if (checkInterval) {
      clearInterval(checkInterval)
    }
    observer.disconnect()
  })

})()