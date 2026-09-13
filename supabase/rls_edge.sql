-- ===========================================================================
-- DepthGuard — Rol restringido para el nodo edge (hallazgo C3)
-- ===========================================================================
--
-- PROBLEMA QUE RESUELVE
-- El edge usaba la service_role key, que salta TODA la RLS por diseno. Quien
-- leyera el .env de esa maquina (acceso fisico, un USB, malware, un backup)
-- obtenia control total del proyecto: todos los usuarios, TODAS LAS PLANTILLAS
-- BIOMETRICAS, todo el historico, y escritura sin restriccion.
--
-- Este script crea un rol que puede hacer EXACTAMENTE lo que el edge necesita
-- y nada mas. La lista de privilegios sale de auditar el codigo y esta
-- declarada en backend/privilegios.py; el test tests/test_privilegios.py falla
-- si el codigo empieza a pedir algo que no este ahi.
--
-- ---------------------------------------------------------------------------
-- ANTES DE EJECUTAR — LEE ESTO
-- ---------------------------------------------------------------------------
-- 1. Ejecuta en un proyecto de PRUEBAS primero. Estas sentencias activan RLS
--    en tablas que quiza hoy no la tienen; si tu frontend accede a ellas con
--    la anon key, dejara de funcionar hasta que anadas sus propias politicas.
--    Este fichero solo cubre el EDGE, no el frontend.
--
-- 2. Revisa que los nombres de columna coinciden con tu esquema real. Estan
--    sacados del codigo del edge, no de un dump de tu base de datos.
--
-- 3. Supabase tiene DOS generaciones de claves:
--      (a) Legado: JWT HS256 firmados con el "JWT secret" del proyecto.
--      (b) Nuevo: claves publishable/secret + claves de firma asimetricas.
--    El paso 5 (acunar el token del dispositivo) es distinto en cada una.
--    Mira Settings > API en tu proyecto para saber en cual estas.
-- ===========================================================================


-- ---------------------------------------------------------------------------
-- 1. El rol del dispositivo
-- ---------------------------------------------------------------------------
-- NOLOGIN: nadie se conecta como este rol directamente.
-- NOINHERIT: no hereda privilegios de otros roles por accidente.
-- Sin BYPASSRLS: justo lo contrario de service_role.

do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'depthguard_edge') then
    create role depthguard_edge nologin noinherit;
  end if;
end
$$;

-- PostgREST cambia a este rol segun el claim del JWT, asi que 'authenticator'
-- debe poder asumirlo.
grant depthguard_edge to authenticator;

grant usage on schema public to depthguard_edge;


-- ---------------------------------------------------------------------------
-- 2. GRANTs por columna
-- ---------------------------------------------------------------------------
-- Se conceden columnas concretas, no la tabla entera: si manana se anade una
-- columna sensible a `usuarios`, el edge no la ve por defecto.

-- usuarios: leer plantillas de gente activa, y escribir SOLO biometria
grant select (id, nombre, embeddings_json, num_angulos, activo)
  on public.usuarios to depthguard_edge;
grant update (embeddings_json, num_angulos)
  on public.usuarios to depthguard_edge;

-- historial: insertar eventos
grant insert on public.historial to depthguard_edge;

-- historial: select/delete SOLO si mantienes la limpieza en el dispositivo.
-- Recomendado: NO concederlos, poner CLEANUP_EN_EDGE=false en el .env y
-- programar la retencion con pg_cron (seccion 6). Un edge comprometido con
-- delete puede borrar el rastro de auditoria.
-- grant select, delete on public.historial to depthguard_edge;

-- estado_sistema: heartbeat y estado de camaras
grant select on public.estado_sistema to depthguard_edge;
grant update (ultimo_heartbeat, camara_activa, modo_camara, camaras,
              tolerancia_facial, umbral_varianza, cooldown_eventos, updated_at)
  on public.estado_sistema to depthguard_edge;

-- comandos_edge: leer pendientes y reportar progreso.
-- Nunca insert ni delete: el edge no crea comandos, solo los ejecuta.
grant select on public.comandos_edge to depthguard_edge;
grant update (estado, progreso, resultado, updated_at)
  on public.comandos_edge to depthguard_edge;

-- Y nada de las tablas prohibidas. Explicito para que quede en el registro:
revoke all on public.admin from depthguard_edge;
revoke all on public.suscripciones_push from depthguard_edge;


-- ---------------------------------------------------------------------------
-- 3. RLS por tabla
-- ---------------------------------------------------------------------------
-- Los GRANT acotan columnas; la RLS acota FILAS. Hacen falta los dos.

alter table public.usuarios        enable row level security;
alter table public.historial       enable row level security;
alter table public.estado_sistema  enable row level security;
alter table public.comandos_edge   enable row level security;

-- usuarios: el edge solo ve usuarios activos
drop policy if exists edge_lee_usuarios_activos on public.usuarios;
create policy edge_lee_usuarios_activos on public.usuarios
  for select to depthguard_edge
  using (activo = true);

-- usuarios: y solo actualiza usuarios activos
drop policy if exists edge_actualiza_biometria on public.usuarios;
create policy edge_actualiza_biometria on public.usuarios
  for update to depthguard_edge
  using (activo = true)
  with check (activo = true);

-- historial: insertar, nunca leer lo que ya hay
drop policy if exists edge_inserta_historial on public.historial;
create policy edge_inserta_historial on public.historial
  for insert to depthguard_edge
  with check (true);

-- estado_sistema: solo la fila del sistema
drop policy if exists edge_lee_estado on public.estado_sistema;
create policy edge_lee_estado on public.estado_sistema
  for select to depthguard_edge
  using (id = 1);

drop policy if exists edge_actualiza_estado on public.estado_sistema;
create policy edge_actualiza_estado on public.estado_sistema
  for update to depthguard_edge
  using (id = 1)
  with check (id = 1);

-- comandos_edge: solo comandos pendientes o en curso
drop policy if exists edge_lee_comandos on public.comandos_edge;
create policy edge_lee_comandos on public.comandos_edge
  for select to depthguard_edge
  using (estado in ('pendiente', 'en_progreso'));

drop policy if exists edge_actualiza_comandos on public.comandos_edge;
create policy edge_actualiza_comandos on public.comandos_edge
  for update to depthguard_edge
  using (estado in ('pendiente', 'en_progreso'));


-- ---------------------------------------------------------------------------
-- 4. Storage
-- ---------------------------------------------------------------------------
-- El edge sube fotos de eventos y el preview en vivo al bucket "capturas".
-- Solo INSERT/UPDATE; el borrado lo hace la retencion de la seccion 6.

drop policy if exists edge_sube_capturas on storage.objects;
create policy edge_sube_capturas on storage.objects
  for insert to depthguard_edge
  with check (bucket_id = 'capturas');

drop policy if exists edge_reemplaza_preview on storage.objects;
create policy edge_reemplaza_preview on storage.objects
  for update to depthguard_edge
  using (bucket_id = 'capturas');

-- NOTA (hallazgo C5, PENDIENTE): el bucket "capturas" es publico hoy. El
-- codigo usa get_public_url(), asi que las fotos faciales de cada evento y el
-- preview en vivo quedan en URLs sin autenticacion ni caducidad, con ruta
-- adivinable (live_preview.jpg). Arreglarlo requiere ademas cambiar el codigo
-- a URLs firmadas, asi que va en su propio cambio.


-- ---------------------------------------------------------------------------
-- 5. Acunar el token del dispositivo
-- ---------------------------------------------------------------------------
-- El token lleva el claim role = 'depthguard_edge'. Genera el JWT FUERA del
-- dispositivo y guarda en el .env SOLO el token resultante:
--
--     SUPABASE_EDGE_KEY=<token>
--     PERMITIR_SERVICE_KEY=false
--     CLEANUP_EN_EDGE=false
--
-- NUNCA guardes el JWT secret del proyecto en el edge: con el se puede acunar
-- un token service_role y volvemos al problema original.
--
-- Claves de LEGADO (JWT secret HS256), en una maquina de administracion:
--
--     python -c "
--     import jwt, time
--     SECRET = 'TU_JWT_SECRET_DEL_PROYECTO'
--     ahora = int(time.time())
--     print(jwt.encode({
--         'role': 'depthguard_edge',
--         'iss': 'supabase',
--         'iat': ahora,
--         'exp': ahora + 60*60*24*365,   # 1 ano; rotalo
--     }, SECRET, algorithm='HS256'))
--     "
--
-- Proyectos con claves NUEVAS (asimetricas): el flujo es distinto. Consulta
-- Settings > API > JWT Keys en tu proyecto, porque el token hay que firmarlo
-- con la clave de firma activa.
--
-- COMPROBACION: con el token puesto, el edge debe arrancar y funcionar, y
-- ademas estas dos cosas deben FALLAR (si no fallan, la RLS no esta puesta):
--   - leer la tabla admin
--   - borrar filas de historial


-- ---------------------------------------------------------------------------
-- 6. Retencion en la base de datos, no en el dispositivo
-- ---------------------------------------------------------------------------
-- Sustituye al hilo de cleanup del edge. Asi el dispositivo no necesita
-- permiso de borrado sobre el rastro de auditoria.
-- Ajusta el intervalo a tu DIAS_RETENCION.

-- create extension if not exists pg_cron;
--
-- select cron.schedule(
--   'depthguard-retencion',
--   '0 3 * * *',                       -- cada dia a las 03:00 UTC
--   $$ delete from public.historial
--      where timestamp < now() - interval '30 days' $$
-- );
--
-- Las fotos huerfanas del Storage se limpian aparte; si no lo haces, el bucket
-- crece indefinidamente aunque el historial se pode.
