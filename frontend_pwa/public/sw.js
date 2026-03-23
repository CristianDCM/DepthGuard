/*
 * Service Worker para DepthGuard
 * Maneja notificaciones push en segundo plano
 * Compatible con Chrome, Edge, y otros navegadores Chromium
 */

// ─── PUSH: Se ejecuta cuando llega una push (incluso con la app cerrada) ───
self.addEventListener('push', function(event) {
    console.log('[SW] Push recibida');

    let datos = {
        titulo: '🛡️ DepthGuard',
        mensaje: 'Nueva alerta de seguridad',
        tipo: 'info'
    };

    // Leer datos enviados desde el servidor
    if (event.data) {
        try {
            datos = event.data.json();
        } catch (e) {
            datos.mensaje = event.data.text();
        }
    }

    const opciones = {
        body: datos.mensaje,
        icon: './assets/icon-192.png',
        badge: './assets/icon-192.png',
        vibrate: [200, 100, 200, 100, 200],
        tag: `depthguard-${datos.tipo}-${Date.now()}`,
        requireInteraction: true,
        silent: false,
        renotify: true,
        actions: [
            { action: 'ver', title: '👁️ Ver detalle' },
            { action: 'cerrar', title: '✖️ Cerrar' }
        ],
        data: {
            url: './',
            tipo: datos.tipo,
            timestamp: new Date().toISOString()
        }
    };

    // Mostrar la notificación + avisar a la página
    event.waitUntil(
        self.registration.showNotification(
            datos.titulo || '🛡️ DepthGuard',
            opciones
        ).then(function() {
            return self.clients.matchAll();
        }).then(function(clientes) {
            clientes.forEach(function(cliente) {
                cliente.postMessage('push-recibido');
            });
        })
    );
});


// ─── CLICK: Se ejecuta cuando el usuario toca la notificación ───
self.addEventListener('notificationclick', function(event) {
    console.log('[SW] Notificación tocada');
    event.notification.close();

    if (event.action === 'cerrar') {
        return;
    }

    // Abrir la app o enfocarla si ya está abierta
    event.waitUntil(
        self.clients.matchAll({
            type: 'window',
            includeUncontrolled: true
        }).then(function(clientes) {
            for (let cliente of clientes) {
                if (cliente.url.includes('/') && 'focus' in cliente) {
                    return cliente.focus();
                }
            }
            return self.clients.openWindow(
                event.notification.data.url || './'
            );
        })
    );
});


// ─── FETCH: Requerido para que Edge no desactive el Service Worker ───
// IMPORTANTE: Solo registrar el listener, NO usar event.respondWith()
// porque interceptar requests rompe el push en background en Chrome.
self.addEventListener('fetch', function(event) {
    // No hacer nada — el browser maneja el request normalmente.
    // Solo la presencia de este listener mantiene el SW activo en Edge.
    return;
});


// ─── PUSH SUBSCRIPTION CHANGE: Re-suscripción automática ───
// Si el navegador renueva la suscripción, re-enviar al servidor.
self.addEventListener('pushsubscriptionchange', function(event) {
    console.log('[SW] Suscripción push cambió, re-suscribiendo...');
    event.waitUntil(
        self.registration.pushManager.subscribe(
            event.oldSubscription.options
        ).then(function(nuevaSub) {
            return fetch('./suscribir', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(nuevaSub.toJSON())
            });
        }).then(function() {
            console.log('[SW] Re-suscripción exitosa');
        }).catch(function(error) {
            console.error('[SW] Error re-suscribiendo:', error);
        })
    );
});


// ─── INSTALL ───
self.addEventListener('install', function(event) {
    console.log('[SW] Instalado');
    self.skipWaiting();
});


// ─── ACTIVATE ───
self.addEventListener('activate', function(event) {
    console.log('[SW] Activado');
    event.waitUntil(self.clients.claim());
});