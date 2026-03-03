/**
 * Cliente SSE (Server-Sent Events) para notificaciones en tiempo real
 *
 * Este cliente maneja la conexión SSE con el servidor, auto-reconexión
 * con exponential backoff, y despacho de eventos personalizados.
 *
 * Uso:
 *   const client = new NotificationSSEClient('/api/core/v1');
 *   client.on('notification', (data) => console.log('Nueva notificación:', data));
 *   client.on('counts', (counts) => console.log('Conteos:', counts));
 *   client.connect();
 */

class NotificationSSEClient {
    constructor(apiBase = '/api/core/v1') {
        this.apiBase = apiBase;
        this.reader = null;
        this.abortController = null;
        this.isConnected = false;
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 10;
        this.baseReconnectDelay = 1000; // 1 segundo
        this.maxReconnectDelay = 30000; // 30 segundos
        this.eventListeners = {};
        this.buffer = ''; // Buffer para acumular chunks incompletos
    }

    /**
     * Conecta al stream SSE
     * No necesita leer el token manualmente, el navegador lo envía automáticamente
     */
    async connect() {
        if (this.isConnected) {
            console.warn('[SSE] Already connected');
            return;
        }

        try {
            this.abortController = new AbortController();

            const response = await fetch(`${this.apiBase}/notifications/stream`, {
                method: 'GET',
                headers: {
                    'Cache-Control': 'no-cache',
                    'Accept': 'text/event-stream'
                },
                credentials: 'include', // Envía cookies automáticamente (incluidas HttpOnly)
                signal: this.abortController.signal
            });

            if (!response.ok) {
                if (response.status === 401) {
                    console.error('[SSE] Authentication failed - token may be expired');
                    this.trigger('auth_error', { status: 401 });
                    return;
                }
                throw new Error(`SSE connection failed: ${response.status}`);
            }

            this.isConnected = true;
            this.reconnectAttempts = 0;
            console.log('[SSE] Connected successfully');
            this.trigger('connected', {});

            // Leer el stream
            this.reader = response.body.getReader();
            const decoder = new TextDecoder();

            while (true) {
                const {value, done} = await this.reader.read();

                if (done) {
                    console.log('[SSE] Stream ended');
                    break;
                }

                // Decodificar y procesar chunk
                const chunk = decoder.decode(value, {stream: true});
                this.processChunk(chunk);
            }

        } catch (error) {
            if (error.name === 'AbortError') {
                console.log('[SSE] Connection aborted');
            } else {
                console.error('[SSE] Connection error:', error);
                this.trigger('error', { message: error.message });
            }
        } finally {
            this.isConnected = false;
            this.attemptReconnect();
        }
    }

    /**
     * Procesa chunks SSE y parsea eventos
     */
    processChunk(chunk) {
        this.buffer += chunk;

        // Dividir por doble newline (separador de eventos SSE)
        const events = this.buffer.split('\n\n');

        // El último elemento puede ser incompleto, guardarlo en buffer
        this.buffer = events.pop();

        // Procesar eventos completos
        for (const eventText of events) {
            if (!eventText.trim()) continue;

            // Parsear evento SSE
            const lines = eventText.split('\n');
            let eventType = 'message';
            let data = '';

            for (const line of lines) {
                if (line.startsWith('event:')) {
                    eventType = line.substring(6).trim();
                } else if (line.startsWith('data:')) {
                    data += line.substring(5).trim();
                }
            }

            if (data) {
                try {
                    const parsed = JSON.parse(data);
                    this.handleEvent(parsed);
                } catch (e) {
                    console.error('[SSE] Failed to parse event data:', data, e);
                }
            }
        }
    }

    /**
     * Maneja eventos SSE parseados
     */
    handleEvent(data) {
        const eventType = data.type || 'notification';

        switch (eventType) {
            case 'connected':
                console.log(`[SSE] Connected as user ${data.user_id}`);
                this.trigger('connected', data);
                if (data.counts) {
                    this.trigger('counts', data.counts);
                }
                break;

            case 'notification':
                // Si el evento completo está en data, usarlo; sino, data es la notificación
                const notification = data.notification || data;
                this.trigger('notification', notification);
                break;

            case 'heartbeat':
                // Silencioso, solo para keep-alive
                break;

            case 'error':
                console.error('[SSE] Server error:', data.message);
                this.trigger('error', data);
                break;

            default:
                // Notificación directa (sin type wrapper)
                if (data.id && data.title) {
                    this.trigger('notification', data);
                } else {
                    console.warn('[SSE] Unknown event type:', eventType, data);
                }
        }
    }

    /**
     * Intenta reconectar con exponential backoff
     */
    attemptReconnect() {
        if (this.reconnectAttempts >= this.maxReconnectAttempts) {
            console.error('[SSE] Max reconnect attempts reached');
            this.trigger('max_reconnect_reached', {});
            return;
        }

        this.reconnectAttempts++;

        // Exponential backoff: 1s, 2s, 4s, 8s, 16s, 30s (max)
        const delay = Math.min(
            this.baseReconnectDelay * Math.pow(2, this.reconnectAttempts - 1),
            this.maxReconnectDelay
        );

        console.log(`[SSE] Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts})`);

        this.trigger('reconnecting', { attempt: this.reconnectAttempts, delay });

        setTimeout(() => {
            this.connect();
        }, delay);
    }

    /**
     * Desconecta el stream SSE
     */
    disconnect() {
        if (this.abortController) {
            this.abortController.abort();
        }
        if (this.reader) {
            this.reader.cancel();
        }
        this.isConnected = false;
        this.reconnectAttempts = this.maxReconnectAttempts; // Prevent auto-reconnect
        console.log('[SSE] Disconnected');
    }

    /**
     * Registra un listener para un tipo de evento
     */
    on(eventType, callback) {
        if (!this.eventListeners[eventType]) {
            this.eventListeners[eventType] = [];
        }
        this.eventListeners[eventType].push(callback);
    }

    /**
     * Remueve un listener
     */
    off(eventType, callback) {
        if (!this.eventListeners[eventType]) return;

        const index = this.eventListeners[eventType].indexOf(callback);
        if (index > -1) {
            this.eventListeners[eventType].splice(index, 1);
        }
    }

    /**
     * Dispara un evento a los listeners registrados
     */
    trigger(eventType, data) {
        const listeners = this.eventListeners[eventType] || [];
        for (const callback of listeners) {
            try {
                callback(data);
            } catch (e) {
                console.error(`[SSE] Error in ${eventType} listener:`, e);
            }
        }
    }

    /**
     * Obtiene el estado de la conexión
     */
    getStatus() {
        return {
            isConnected: this.isConnected,
            reconnectAttempts: this.reconnectAttempts
        };
    }
}

// Exportar para uso global
if (typeof window !== 'undefined') {
    window.NotificationSSEClient = NotificationSSEClient;
}
