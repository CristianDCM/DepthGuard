-- ===========================================================================
-- DepthGuard — Autorizacion del canal de senalizacion WebRTC (hallazgo C2)
-- ===========================================================================
--
-- QUE ESTA MAL
-- ------------
-- La senalizacion usa un canal Broadcast de Supabase Realtime llamado
-- `webrtc-signaling-{camera_id}`, y camera_id es un valor fijo del codigo:
-- "entrada_principal" o "entrada_secundaria". O sea, nombre predecible.
--
-- El edge respondia a CUALQUIER oferta SDP que llegara a ese canal
-- (_manejar_offer no comprobaba nada). Quien pudiera suscribirse obtenia
-- video en vivo de la camara.
--
-- POR QUE NO SE ARREGLA EN EL EDGE
-- --------------------------------
-- Sobre un canal Broadcast, el edge no puede autenticar a su interlocutor.
-- Ni siquiera pidiendole un token: un token enviado por broadcast lo reciben
-- TODOS los suscriptores del canal, asi que pedirlo filtraria justo la
-- credencial que se pretendia comprobar.
--
-- La autorizacion tiene que aplicarla el transporte. Supabase lo llama
-- Realtime Authorization: un canal declarado `private` evalua la RLS de
-- `realtime.messages` antes de dejar que alguien se una o publique.
--
-- ---------------------------------------------------------------------------
-- ORDEN DE APLICACION (importante)
-- ---------------------------------------------------------------------------
--   1. Este SQL.
--   2. Frontend: setAuth() + { config: { private: true } }  (ver abajo).
--   3. Edge: WEBRTC_CANAL_PRIVADO=true en el .env.
--
-- Si haces (1) y (3) sin (2), el panel deja de recibir video.
-- Si haces solo (1), no rompes nada: las politicas no se aplican hasta que
-- alguien declara el canal como privado.
-- ===========================================================================


-- ---------------------------------------------------------------------------
-- 1. Politicas del canal
-- ---------------------------------------------------------------------------
-- En realtime.messages, `extension` dice el tipo de mensaje ('broadcast' o
-- 'presence') y realtime.topic() da el nombre del canal.
--
--   SELECT -> puede unirse al canal y recibir
--   INSERT -> puede publicar en el canal
--
-- Se acota por prefijo de topic para no abrir todos los canales Realtime del
-- proyecto de golpe.

-- --- El panel: cualquier usuario con sesion iniciada ---
-- En este proyecto todo usuario autenticado es administrador (el rol vive en
-- app_metadata.role y list-admins trata como "admin" a quien no lo tenga).

drop policy if exists webrtc_panel_recibe on realtime.messages;
create policy webrtc_panel_recibe on realtime.messages
  for select to authenticated
  using (
    realtime.messages.extension = 'broadcast'
    and realtime.topic() like 'webrtc-signaling-%'
  );

drop policy if exists webrtc_panel_publica on realtime.messages;
create policy webrtc_panel_publica on realtime.messages
  for insert to authenticated
  with check (
    realtime.messages.extension = 'broadcast'
    and realtime.topic() like 'webrtc-signaling-%'
  );

-- --- El nodo edge ---
-- Se une con su clave restringida (rol depthguard_edge), no con la anon:
-- la anon no pasaria una politica escrita para identidades autenticadas.
-- Ese es el intercambio de WEBRTC_CANAL_PRIVADO, y es favorable: la clave del
-- edge sigue acotada por su propia RLS, y a cambio nadie no autorizado puede
-- siquiera entrar en el canal.
--
-- Si todavia no has migrado la clave del edge, este rol no existe: comenta
-- estas dos politicas. El edge seguira usando service_role, que se salta la
-- RLS y entra igual.

drop policy if exists webrtc_edge_recibe on realtime.messages;
create policy webrtc_edge_recibe on realtime.messages
  for select to depthguard_edge
  using (
    realtime.messages.extension = 'broadcast'
    and realtime.topic() like 'webrtc-signaling-%'
  );

drop policy if exists webrtc_edge_publica on realtime.messages;
create policy webrtc_edge_publica on realtime.messages
  for insert to depthguard_edge
  with check (
    realtime.messages.extension = 'broadcast'
    and realtime.topic() like 'webrtc-signaling-%'
  );


-- ---------------------------------------------------------------------------
-- 2. Cambio en el frontend (DepthGuard_Design)
-- ---------------------------------------------------------------------------
-- En src/components/WebRTCPlayer.tsx, donde hoy pone:
--
--     const canalNombre = `webrtc-signaling-${cameraId}`;
--     const canal = supabase.channel(canalNombre);
--
-- queda:
--
--     const canalNombre = `webrtc-signaling-${cameraId}`;
--     await supabase.realtime.setAuth();          // identidad de la sesion
--     const canal = supabase.channel(canalNombre, {
--       config: { private: true },
--     });
--
-- setAuth() es imprescindible: sin el, la conexion Realtime no lleva el JWT
-- de la sesion y la RLS no tiene identidad contra la que evaluar.


-- ---------------------------------------------------------------------------
-- 3. Comprobacion de aceptacion
-- ---------------------------------------------------------------------------
-- 1. Las politicas existen:
--
--      select policyname, roles, cmd
--      from pg_policies
--      where schemaname = 'realtime' and tablename = 'messages'
--      order by policyname;
--
-- 2. Con sesion iniciada, el monitor en vivo del panel sigue funcionando.
--
-- 3. SIN sesion (solo la clave anon), suscribirse a
--    `webrtc-signaling-entrada_principal` como canal privado debe FALLAR con
--    un error de autorizacion. Antes devolvia video.
--
-- 4. En los logs del edge debe aparecer "canal PRIVADO (autorizacion por
--    RLS)" y no el aviso de canal publico.
