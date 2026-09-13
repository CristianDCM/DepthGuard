-- ===========================================================================
--  RETENCION DE DATOS — lado base de datos
-- ===========================================================================
--
-- Sustituye al hilo de cleanup del edge, que NO PODIA funcionar: el rol del
-- dispositivo no tiene lectura sobre historial (ni debe tenerla), asi que la
-- consulta que busca los registros caducados fallaba con 42501 antes de llegar
-- a borrar nada. El sintoma era un error cada 24 horas seguido de un
-- "nada que limpiar" que era falso.
--
-- Este fichero es el estado REAL aplicado al proyecto, no una plantilla:
-- ya esta en produccion. Se conserva versionado para poder auditarlo y
-- reconstruirlo.
--
-- Reparto de responsabilidades:
--   * Aqui: encontrar que sobra, guardar el token, y disparar el trabajo.
--   * supabase/functions/retencion/index.ts: borrar, foto primero y fila
--     despues.
--
-- Por que la parte que borra no esta aqui: las fotos no se pueden borrar por
-- SQL. Borrar filas de storage.objects deja el fichero fisico en el bucket y
-- se sigue facturando (queda un huerfano inalcanzable). La propia base de
-- datos lo impide con un trigger:
--     ERROR: Direct deletion from storage tables is not allowed.
--            Use the Storage API instead.
-- Y a la Storage API no se llega desde Postgres. De ahi la Edge Function.


-- ---------------------------------------------------------------------------
-- 1. Localizar fotos huerfanas
-- ---------------------------------------------------------------------------
create or replace function public.fotos_huerfanas(
  dias_min int,
  limite_filas int default 1000
)
returns table (nombre text)
language sql
security definer
set search_path = public, storage, pg_temp
as $$
  with referenciadas as (
    -- Mismo despiece que hace la Edge Function sobre foto_url:
    -- https://<ref>.../object/public/capturas/<nombre>.jpg?  ->  <nombre>.jpg
    select split_part(split_part(foto_url, '/capturas/', 2), '?', 1) as nombre
    from public.historial
    where foto_url is not null
  )
  select o.name
  from storage.objects o
  where o.bucket_id = 'capturas'
    -- El preview en vivo se sobreescribe cada 2 s y no pertenece a ningun
    -- evento: por viejo que sea su created_at, nunca es un huerfano.
    and o.name <> 'live_preview.jpg'
    -- Se exige que el objeto sea MAS VIEJO que la ventana de retencion antes
    -- de declararlo huerfano. El edge bufferea eventos cuando pierde la red,
    -- asi que una foto puede llevar horas en el bucket antes de que llegue su
    -- fila; sin esta condicion se borraria la foto de un evento aun por subir.
    and o.created_at < now() - make_interval(days => dias_min)
    and not exists (
      select 1 from referenciadas r where r.nombre = o.name
    )
  limit limite_filas;
$$;

-- Solo el trabajo de retencion la ejecuta. Ni el edge ni el frontend tienen
-- nada que hacer con la lista de objetos del bucket.
revoke all on function public.fotos_huerfanas(int, int) from public;
revoke all on function public.fotos_huerfanas(int, int) from anon, authenticated;
grant execute on function public.fotos_huerfanas(int, int) to service_role;


-- ---------------------------------------------------------------------------
-- 2. Token que autoriza la invocacion
-- ---------------------------------------------------------------------------
-- La Edge Function esta protegida con verify_jwt, pero la clave ANON tambien
-- es un JWT valido y es publica (esta en el frontend). Sin una comprobacion
-- adicional cualquiera podria disparar un trabajo que borra datos.
--
-- Y no se usa la clave de servicio como token porque habria que guardarla
-- aqui, y esa clave salta toda la RLS del proyecto. Este token sirve para una
-- sola cosa y se genera DENTRO de la base de datos: no aparece en el codigo,
-- ni en la configuracion de la funcion, ni en el comando del cron (que lo lee
-- del Vault en tiempo de ejecucion). Nadie tiene que copiarlo a ningun sitio,
-- asi que no puede filtrarse por el camino.

do $$
declare
  ya_existe uuid;
begin
  select id into ya_existe from vault.secrets where name = 'retencion_token';

  if ya_existe is null then
    perform vault.create_secret(
      encode(gen_random_bytes(32), 'hex'),
      'retencion_token',
      'Autoriza la invocacion de la Edge Function "retencion" desde pg_cron.'
    );
  end if;
end $$;


-- Comprueba el token SIN devolverlo: la funcion pregunta "es valido esto?" en
-- vez de pedir "dame el secreto", asi que el token nunca sale de la base de
-- datos ni siquiera hacia quien lo verifica.
create or replace function public.retencion_token_valido(token text)
returns boolean
language plpgsql
security definer
set search_path = vault, pg_temp
as $$
declare
  esperado text;
begin
  select decrypted_secret into esperado
  from vault.decrypted_secrets
  where name = 'retencion_token';

  if esperado is null or token is null then
    return false;
  end if;

  -- Comparacion de tiempo constante: comparar los hashes en vez de las cadenas
  -- evita que el tiempo de respuesta revele cuantos caracteres iniciales ha
  -- acertado quien lo intenta.
  --
  -- hmac() se cualifica con su esquema a proposito. Es de pgcrypto, que en
  -- Supabase vive en "extensions", y con el search_path cerrado no se
  -- encontraba: la funcion fallaba en CADA invocacion y el cron nunca habria
  -- podido ejecutar la retencion. Se cualifica en vez de ampliar el
  -- search_path, porque tenerlo cerrado es lo que impide que alguien coloque
  -- una funcion homonima en un esquema intermedio.
  return length(token) = length(esperado)
     and extensions.hmac(token, 'cmp', 'sha256')
       = extensions.hmac(esperado, 'cmp', 'sha256');
end $$;

revoke all on function public.retencion_token_valido(text) from public;
revoke all on function public.retencion_token_valido(text) from anon, authenticated;
grant execute on function public.retencion_token_valido(text) to service_role;


-- ---------------------------------------------------------------------------
-- 3. Programacion diaria
-- ---------------------------------------------------------------------------
-- La clave anon va en Authorization solo para satisfacer el gateway. Es
-- publica, ya esta en el frontend, y no autoriza nada por si misma: la
-- autorizacion real es x-retencion-token, que se lee del Vault en cada
-- ejecucion y por tanto no aparece escrito en ninguna parte.
--
-- Sustituye <REF> por la referencia del proyecto y <ANON_KEY> por la clave
-- publica si se reconstruye en otro proyecto.

create extension if not exists pg_cron;

-- Idempotente: si ya estaba programada se reemplaza en vez de duplicarse.
select cron.unschedule('depthguard-retencion')
where exists (select 1 from cron.job where jobname = 'depthguard-retencion');

select cron.schedule(
  'depthguard-retencion',
  '0 7 * * *',   -- 07:00 UTC = 02:00 en Colombia (UTC-5), fuera de horario
  $cron$
  select net.http_post(
    url := 'https://<REF>.supabase.co/functions/v1/retencion',
    headers := jsonb_build_object(
      'Content-Type', 'application/json',
      'Authorization', 'Bearer <ANON_KEY>',
      'x-retencion-token', (
        select decrypted_secret from vault.decrypted_secrets
        where name = 'retencion_token'
      )
    ),
    body := '{}'::jsonb,
    -- La funcion puede tardar: hasta 10 lotes de 200 fotos por la Storage API.
    timeout_milliseconds := 150000
  );
  $cron$
);


-- ---------------------------------------------------------------------------
-- 4. Como comprobar que sigue funcionando
-- ---------------------------------------------------------------------------
-- Que esta programada y cuando corrio:
--   select jobname, schedule, active from cron.job;
--   select status, return_message, start_time
--   from cron.job_run_details
--   where jobname = 'depthguard-retencion'
--   order by start_time desc limit 10;
--
-- Que devolvio la funcion (pg_cron solo ve que el POST se envio; el resultado
-- del trabajo esta en la respuesta HTTP):
--   select status_code, content, created
--   from net._http_response order by id desc limit 10;
--
-- Que nada caducado se ha quedado atras:
--   select count(*) from public.historial
--   where timestamp < now() - interval '30 days';
--   select count(*) from public.fotos_huerfanas(30, 5000);
--
-- Cuanto pesa el bucket:
--   select count(*), pg_size_pretty(sum((metadata->>'size')::bigint))
--   from storage.objects where bucket_id = 'capturas';
--
-- Para ejecutarla a mano (mismo camino que el cron):
--   select net.http_post( ... ) -- copiar el bloque de la seccion 3
