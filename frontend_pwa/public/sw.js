/*
 * Service Worker para DepthGuard
 * Maneja notificaciones push en segundo plano
 */

// Se ejecuta cuando llega una push (incluso con la app cerrada)
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

    // Icono según tipo de alerta
    const iconos = {
        fraude:  '🚨',
        acceso:  '✅',
        desconocido: '❓',
        info: '🛡️'
    };

    const opciones = {
        body: datos.mensaje,
        icon: '/static/icon-192.png',
        badge: '/static/icon-192.png',
        vibrate: [200, 100, 200, 100, 200],
        tag: `depthguard-${datos.tipo}-${Date.now()}`,
        requireInteraction: true,
        actions: [
            { action: 'ver', title: '👁️ Ver detalle' },
            { action: 'cerrar', title: '✖️ Cerrar' }
        ],
        data: {
            url: '/',
            tipo: datos.tipo,
            timestamp: new Date().toISOString()
        }
    };

    // Mostrar la notificación
    event.waitUntil(
        self.registration.showNotification(
            datos.titulo || '🛡️ DepthGuard',
            opciones
        )
    );

    // Avisar a la página (si está abierta) que llegó una push
    event.waitUntil(
        self.clients.matchAll().then(function(clientes) {
            clientes.forEach(function(cliente) {
                cliente.postMessage('push-recibido');
            });
        })
    );
});


// Se ejecuta cuando el usuario toca la notificación
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
            // Si ya hay una ventana abierta, enfocarla
            for (let cliente of clientes) {
                if (cliente.url.includes('/') && 'focus' in cliente) {
                    return cliente.focus();
                }
            }
            // Si no hay ventana, abrir una nueva
            return self.clients.openWindow(
                event.notification.data.url || '/'
            );
        })
    );
});


// Instalación del Service Worker
self.addEventListener('install', function(event) {
    console.log('[SW] Instalado');
    self.skipWaiting();
});

// Activación
self.addEventListener('activate', function(event) {
    console.log('[SW] Activado');
    event.waitUntil(self.clients.claim());
});