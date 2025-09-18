class WindowsDesktop {
  constructor() {
    this.openWindows = []
    this.windowZIndex = 1000
    this.init()
  }

  init() {
    lucide.createIcons()
    this.setupDesktopIcons()
    this.setupPostMessageListener() // Nueva función
    this.updateDateTime()
    setInterval(() => this.updateDateTime(), 1000)
  }

  // Nueva función para escuchar mensajes de los iframes
  setupPostMessageListener() {
    window.addEventListener('message', (event) => {
      // Verificar que el mensaje viene de tu dominio
      if (event.origin !== window.location.origin) {
        return
      }

      // Manejar diferentes tipos de mensajes
      switch (event.data.type) {
        case 'LOGOUT':
          console.log('Logout detectado desde iframe:', event.data)
          this.handleLogout()
          break
        case 'SESSION_EXPIRED':
          console.log('Sesión expirada detectada desde iframe:', event.data)
          this.handleSessionExpired()
          break
        case 'NAVIGATION':
          // Actualizar la URL mostrada en la ventana
          this.updateWindowUrl(event.data.source, event.data.url)
          break
      }
    })
  }

  handleLogout() {
    // Mostrar mensaje de logout si es necesario
    console.log('Cerrando sesión en dashboard principal...')
    
    // Cerrar todas las ventanas
    this.closeAllWindows()
    
    // Recargar la página principal para limpiar el estado
    window.location.href = '/auth/login'
  }

  handleSessionExpired() {
    console.log('Sesión expirada, redirigiendo...')
    this.closeAllWindows()
    window.location.href = '/auth/login?session_expired=true'
  }

  closeAllWindows() {
    // Cerrar todas las ventanas abiertas
    this.openWindows.forEach(appId => {
      const window = document.querySelector(`[data-app-id="${appId}"]`)
      if (window) {
        window.remove()
      }
    })
    this.openWindows = []
    this.updateTaskbar()
  }

  updateWindowUrl(source, url) {
    // Encontrar la ventana que envió el mensaje y actualizar su URL
    const windows = document.querySelectorAll('.app-window')
    windows.forEach(window => {
      const iframe = window.querySelector('.window-iframe')
      if (iframe.contentWindow === source) {
        const urlSpan = window.querySelector('.window-url')
        if (urlSpan) {
          urlSpan.textContent = url
        }
      }
    })
  }

  createWindow(appId, config) {
    const window = document.createElement("div")
    window.className = "app-window"
    window.style.width = "800px"
    window.style.height = "600px"
    window.style.left = "100px"
    window.style.top = "100px"
    window.style.zIndex = ++this.windowZIndex
    window.dataset.appId = appId

    window.innerHTML = `
        <div class="window-titlebar">
            <div class="window-title">
                <span class="window-title-text">${config.name}</span>
                <span class="window-url">${config.url}</span>
            </div>
            <div class="window-controls">
                <button class="window-control minimize">
                    <i data-lucide="minus"></i>
                </button>
                <button class="window-control maximize">
                    <i data-lucide="square"></i>
                </button>
                <button class="window-control close">
                    <i data-lucide="x"></i>
                </button>
            </div>
        </div>
        <div class="window-content">
            <iframe class="window-iframe" 
                    src="${config.iframeSrc}" 
                    title="${config.name} Application" 
                    sandbox="allow-scripts allow-same-origin allow-forms allow-popups">
            </iframe>
        </div>
    `

    this.setupWindowControls(window, appId)
    this.setupWindowDragging(window)
    this.setupIframeMonitoring(window, appId) // Nueva función

    document.getElementById("windows-container").appendChild(window)
    this.openWindows.push(appId)
    this.updateTaskbar()

    lucide.createIcons()
    return window
  }

  setupIframeMonitoring(window, appId) {
    const iframe = window.querySelector(".window-iframe")
    const urlSpan = window.querySelector(".window-url")

    // Monitorear cambios de URL con un polling más inteligente
    let lastUrl = iframe.src
    const checkUrlChange = () => {
      try {
        const currentUrl = iframe.contentWindow.location.href
        if (currentUrl !== lastUrl) {
          lastUrl = currentUrl
          const pathname = new URL(currentUrl).pathname
          urlSpan.textContent = pathname
          
          // Verificar si es logout
          if (pathname.endsWith('/logout') || pathname === '/auth/login') {
            console.log('Logout detectado via URL monitoring:', pathname)
            this.handleLogout()
            return
          }
        }
      } catch (e) {
        // Si no podemos acceder al contentWindow, usar el src del iframe
        if (iframe.src !== lastUrl) {
          lastUrl = iframe.src
          const pathname = new URL(iframe.src, window.location.origin).pathname
          urlSpan.textContent = pathname
        }
      }
    }

    // Verificar cambios cada 500ms solo si la ventana está visible
    const urlChecker = setInterval(() => {
      if (this.openWindows.includes(appId)) {
        checkUrlChange()
      } else {
        clearInterval(urlChecker)
      }
    }, 500)

    // También escuchar el evento load como respaldo
    iframe.addEventListener('load', checkUrlChange)
  }

  // Resto de tu código existente...
  setupDesktopIcons() {
    const desktopIcons = document.querySelectorAll(".desktop-icon[data-app]")

    desktopIcons.forEach((icon) => {
      let clickCount = 0
      let clickTimer = null

      icon.addEventListener("click", (e) => {
        e.preventDefault()
        document.querySelectorAll(".desktop-icon").forEach((i) => i.classList.remove("selected"))
        icon.classList.add("selected")

        clickCount++
        if (clickCount === 1) {
          clickTimer = setTimeout(() => {
            clickCount = 0
          }, 300)
        } else if (clickCount === 2) {
          clearTimeout(clickTimer)
          clickCount = 0
          const appId = icon.dataset.app
          this.openApplication(appId)
        }
      })
    })
  }

  openApplication(appId) {
    if (this.openWindows.includes(appId)) {
      return
    }

    const appConfig = this.getAppConfig(appId)
    this.createWindow(appId, appConfig)
  }

  getAppConfig(appId) {
    const configs = {
      agendatec: {
        name: "AgendaTec",
        url: "/agendatec/",
        iframeSrc: "/agendatec/",
        icon: "calendar",
      },
      compras: {
        name: "Compras", 
        url: "/compras/dashboard",
        iframeSrc: "/compras/",
        icon: "shopping-cart",
      },
      tickets: {
        name: "Tickets",
        url: "/tickets/", 
        iframeSrc: "/tickets/",
        icon: "ticket",
      },
      papelera: {
        name: "Papelera",
        url: "/api/auth/v1/auth/logout",
        iframeSrc: "/api/auth/v1/auth/logout",
        icon: "trash-2",
      }
    }

    return configs[appId] || { 
      name: "App", 
      url: "/app/home", 
      iframeSrc: "/app/home", 
      icon: "square" 
    }
  }

  setupWindowControls(window, appId) {
    const closeBtn = window.querySelector(".window-control.close")
    const maximizeBtn = window.querySelector(".window-control.maximize")

    closeBtn.addEventListener("click", () => {
      this.closeWindow(appId)
    })

    maximizeBtn.addEventListener("click", () => {
      window.classList.toggle("maximized")
    })
  }

  setupWindowDragging(window) {
    const titlebar = window.querySelector(".window-titlebar")
    let isDragging = false
    let dragStart = { x: 0, y: 0 }
    let windowStart = { x: 0, y: 0 }

    titlebar.addEventListener("mousedown", (e) => {
      if (window.classList.contains("maximized")) return

      isDragging = true
      dragStart = { x: e.clientX, y: e.clientY }
      windowStart = {
        x: Number.parseInt(window.style.left) || 0,
        y: Number.parseInt(window.style.top) || 0,
      }

      window.style.zIndex = ++this.windowZIndex
    })

    document.addEventListener("mousemove", (e) => {
      if (!isDragging) return

      const deltaX = e.clientX - dragStart.x
      const deltaY = e.clientY - dragStart.y

      window.style.left = windowStart.x + deltaX + "px"
      window.style.top = windowStart.y + deltaY + "px"
    })

    document.addEventListener("mouseup", () => {
      isDragging = false
    })
  }

  closeWindow(appId) {
    const window = document.querySelector(`[data-app-id="${appId}"]`)
    if (window) {
      window.remove()
    }

    this.openWindows = this.openWindows.filter((id) => id !== appId)
    this.updateTaskbar()
  }

  updateTaskbar() {
    const openAppsContainer = document.getElementById("open-apps")
    openAppsContainer.innerHTML = ""

    this.openWindows.forEach((appId) => {
      const config = this.getAppConfig(appId)
      const button = document.createElement("button")
      button.className = "open-app"
      button.innerHTML = `
                <i data-lucide="${config.icon}"></i>
                ${config.name}
            `

      button.addEventListener("click", () => {
        const window = document.querySelector(`[data-app-id="${appId}"]`)
        if (window) {
          window.style.zIndex = ++this.windowZIndex
        }
      })

      openAppsContainer.appendChild(button)
    })

    lucide.createIcons()
  }

  updateDateTime() {
    const now = new Date()

    const timeElement = document.getElementById("time")
    const dateElement = document.getElementById("date")

    if (timeElement) {
      timeElement.textContent = now.toLocaleTimeString("es-ES", {
        hour: "2-digit",
        minute: "2-digit",
      })
    }

    if (dateElement) {
      dateElement.textContent = now.toLocaleDateString("es-ES", {
        day: "2-digit",
        month: "2-digit",
        year: "numeric",
      })
    }
  }
}

document.addEventListener("DOMContentLoaded", () => {
  const desktop = new WindowsDesktop()

  const logoutBtn = document.getElementById("logout-fab")
  if (logoutBtn) {
    logoutBtn.addEventListener("click", async () => {
      try {
        await fetch("/api/auth/v1/auth/logout", { method: "POST", credentials: "include" })
      } catch (e) {
        // ignoramos errores de red; forzamos logout del lado cliente
      }
      desktop.closeAllWindows()
      window.location.href = "/auth/login"
    })
  }
})
