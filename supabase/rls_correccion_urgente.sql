-- ===========================================================================
-- DepthGuard — CORRECCION URGENTE DE RLS
-- ===========================================================================
--
-- QUE ESTA MAL
-- ------------
-- Cuatro politicas se llaman "Escritura service role ..." pero se crearon
-- sobre el rol `public`:
--
--   Escritura service role usuarios   -> {public}  ALL  using(true) check(true)
--   Escritura service role historial  -> {public}  ALL  using(true) check(true)
--   Escritura service role estado     -> {public}  ALL  using(true) check(true)
--   Escritura service role push       -> {public}  ALL  using(true) check(true)
--
-- En Postgres `public` NO significa "los usuarios autenticados": significa
-- TODOS los roles, `anon` incluido. Y `anon` es la clave que va en el bundle
-- JavaScript de la web, o sea que la tiene cualquiera que abra el panel y
-- mire el codigo fuente.
--
-- IMPACTO ACTUAL, SIN INICIAR SESION
--   * usuarios: LECTURA y ESCRITURA. Descargar todas las plantillas
--     biometricas, y sobrescribirlas. Suplantacion directa, sin pasar
--     siquiera por el nodo edge.
--   * historial: leer, BORRAR el rastro de auditoria, o inyectar accesos
--     falsos.
--   * estado_sistema: escritura.
--   * suscripciones_push: la politica correcta (auth.uid() = user_id) queda
--     ANULADA, porque las politicas se combinan con OR y basta con que una
--     permita.
--
-- POR QUE PASO
-- ------------
-- `CREATE POLICY ... FOR ALL USING (true)` sin clausula `TO` aplica el
-- default de Postgres, que es `public`. La intencion era `TO service_role`.
--
-- Y el detalle que lo hace mas absurdo: esas cuatro politicas NUNCA hicieron
-- falta. `service_role` tiene BYPASSRLS, se salta la RLS por definicion y no
-- necesita politica ninguna. Se eliminan, no se corrigen.
--
-- ---------------------------------------------------------------------------
-- ESTE FICHERO ES SEGURO DE EJECUTAR TAL CUAL
-- ---------------------------------------------------------------------------
-- Las politicas nuevas dan a `authenticated` exactamente lo que el panel usa
-- hoy, verificado leyendo el frontend:
--
--   usuarios        select, insert, update, delete
--   historial       select
--   estado_sistema  select
--   comandos_edge   select, insert
--   suscripciones_push  upsert/delete de las filas propias
--
-- Todas las rutas con datos van detras de <ProtectedRoute>; las unicas
-- publicas son "/" (Login) y "/auth/callback", que no leen estas tablas. Asi
-- que pasar de `public` a `authenticated` no rompe la aplicacion.
--
-- El edge tampoco se ve afectado: hoy usa service_role (salta la RLS) y,
-- cuando migre a `depthguard_edge`, sus permisos vienen de rls_edge.sql.
-- ===========================================================================


-- ---------------------------------------------------------------------------
-- ANTES: deja constancia de como estaba
-- ---------------------------------------------------------------------------
-- select tablename, policyname, roles, cmd from pg_policies
-- where schemaname = 'public' order by tablename, policyname;


begin;

-- ---------------------------------------------------------------------------
-- 1. Eliminar las politicas abiertas a `public`
-- ---------------------------------------------------------------------------

drop policy if exists "Escritura service role usuarios"  on public.usuarios;
drop policy if exists "Lectura pública usuarios"         on public.usuarios;

drop policy if exists "Escritura service role historial" on public.historial;
drop policy if exists "Lectura pública historial"        on public.historial;

drop policy if exists "Escritura service role estado"    on public.estado_sistema;
drop policy if exists "Lectura pública estado"           on public.estado_sistema;

drop policy if exists "Escritura service role push"      on public.suscripciones_push;

-- Redundante: service_role ya se salta la RLS.
drop policy if exists "Service role tiene acceso completo" on public.comandos_edge;


-- ---------------------------------------------------------------------------
-- 2. usuarios — solo usuarios autenticados
-- ---------------------------------------------------------------------------
-- El panel da de alta, edita y borra usuarios, asi que necesita las cuatro
-- operaciones. Lo que cambia es QUIEN: antes cualquiera, ahora solo con
-- sesion iniciada.

create policy usuarios_lectura_autenticada on public.usuarios
  for select to authenticated using (true);

create policy usuarios_alta_autenticada on public.usuarios
  for insert to authenticated with check (true);

create policy usuarios_edicion_autenticada on public.usuarios
  for update to authenticated using (true) with check (true);

create policy usuarios_baja_autenticada on public.usuarios
  for delete to authenticated using (true);


-- ---------------------------------------------------------------------------
-- 3. historial — solo lectura
-- ---------------------------------------------------------------------------
-- El panel unicamente consulta el historial (17 lecturas, ninguna escritura).
-- Quien escribe es el edge, y lo hace con su propio rol. Sin politica de
-- insert/update/delete para `authenticated`, el rastro de auditoria deja de
-- poder alterarse desde el navegador.

create policy historial_lectura_autenticada on public.historial
  for select to authenticated using (true);


-- ---------------------------------------------------------------------------
-- 4. estado_sistema — solo lectura
-- ---------------------------------------------------------------------------
-- El panel lo lee para el heartbeat y el estado de camaras. Lo escribe el edge.

create policy estado_lectura_autenticada on public.estado_sistema
  for select to authenticated using (true);


-- ---------------------------------------------------------------------------
-- 5. suscripciones_push
-- ---------------------------------------------------------------------------
-- "Escritura service role push" ({public} ALL true) ya se elimino arriba: con
-- ella cualquiera leia y escribia las suscripciones de todos, anulando la
-- politica buena.
--
-- La politica buena, `auth.uid() = user_id`, se vuelve a crear acotada a
-- `authenticated`. Estaba sobre `public`, lo que en la practica no abria nada
-- (auth.uid() es NULL sin sesion, y NULL = user_id nunca es cierto), pero
-- dejarla ahi haria que la comprobacion de aceptacion de abajo —"ninguna
-- politica sobre public o anon"— devolviera una fila y pareciera un fallo.

drop policy if exists "Admins manage own push subscriptions" on public.suscripciones_push;

create policy push_propias_autenticadas on public.suscripciones_push
  for all to authenticated
  using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);


commit;


-- ---------------------------------------------------------------------------
-- DESPUES: comprobacion de aceptacion
-- ---------------------------------------------------------------------------
-- 1. Ninguna politica debe quedar sobre `public` ni `anon`:
--
--      select tablename, policyname, roles, cmd
--      from pg_policies
--      where schemaname = 'public'
--        and (roles::text[] && array['public','anon'])
--      order by tablename;
--
--    Debe devolver CERO filas.
--
-- 2. Con la clave anon y SIN sesion, esto debe fallar o venir vacio:
--      GET  /rest/v1/usuarios?select=embeddings_json
--    Antes devolvia todas las plantillas biometricas.
--
-- 3. Inicia sesion en el panel y recorre: dashboard, historial, detalle de
--    evento, alta/edicion/baja de usuario, monitor en vivo. Todo debe seguir
--    funcionando igual.


-- ---------------------------------------------------------------------------
-- APARTE: el bucket de capturas (hallazgo C5)
-- ---------------------------------------------------------------------------
-- `capturas` sigue con public = true, asi que las fotos faciales de cada
-- acceso y el preview en vivo son legibles por cualquiera con la URL.
--
-- NO se incluye aqui porque, a diferencia de todo lo de arriba, cerrarlo SI
-- rompe el frontend hasta coordinar los tres pasos descritos en
-- supabase/rls_edge.sql seccion 4:
--   1. que el frontend lea preview_url de estado_sistema.camaras
--   2. este cambio
--   3. STORAGE_PRIVADO=true en el .env del edge
--
--   update storage.buckets set public = false where id = 'capturas';
--
--   create policy capturas_lectura_autenticada on storage.objects
--     for select to authenticated using (bucket_id = 'capturas');
