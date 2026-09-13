// Retencion de datos de DepthGuard.
//
// Borra los eventos mas antiguos que DIAS_RETENCION en el orden que importa:
// FOTO PRIMERO, FILA DESPUES.
//
// Por que existe esta funcion en vez de un simple pg_cron con un DELETE:
// las fotos no se pueden borrar por SQL. La documentacion de Supabase es
// explicita — borrar filas de storage.objects deja el fichero fisico en el
// bucket y se sigue facturando, convirtiendolo en un huerfano inalcanzable.
// Solo la Storage API borra de verdad, y a la Storage API no se llega desde
// Postgres. De hecho la propia base de datos lo impide: un trigger
// storage.protect_delete() rechaza el DELETE directo con
// "Direct deletion from storage tables is not allowed".
//
// Y el ORDEN importa por el modo de fallo. Si se borrara la fila primero se
// perderia el unico puntero que existe al nombre de la foto, y un fallo a
// mitad dejaria la foto huerfana para siempre. Borrando la foto primero, un
// fallo deja la fila intacta y manana se reintenta: se renuncia a la
// idempotencia facil a cambio de no perder nada de forma irrecuperable.
//
// Despliegue: no se despliega desde este repo, vive en el proyecto Supabase.
// Esta copia es la fuente de verdad para revisarla y versionarla.
//   supabase functions deploy retencion
// La programa pg_cron; ver supabase/retencion.sql.

import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "jsr:@supabase/supabase-js@2";

const BUCKET = "capturas";

// El preview en vivo se sobreescribe cada 2 segundos y no pertenece a ningun
// evento, asi que por viejo que sea nunca es un huerfano.
const PREVIEW = "live_preview.jpg";

// remove() de la Storage API acepta 1000 rutas como maximo. Se usa un lote
// menor para que cada vuelta termine holgadamente dentro del tiempo limite.
const LOTE = 200;

// Tope de vueltas por invocacion: hasta 2000 eventos al dia, muy por encima
// del ritmo real (~2400 al mes). Evita que una invocacion se eternice si
// algun dia aparece un backlog enorme.
const MAX_LOTES = 10;

const dias = Number(Deno.env.get("DIAS_RETENCION") ?? "30");

function nombreDeFoto(url: string | null): string | null {
  // foto_url es del tipo
  //   https://<ref>.supabase.co/storage/v1/object/public/capturas/acceso_X.jpg?
  // y el nombre del objeto en el bucket es el ultimo segmento, sin query.
  if (!url) return null;
  const partes = url.split(`/${BUCKET}/`);
  if (partes.length < 2) return null;
  const nombre = partes[partes.length - 1].split("?")[0].trim();
  return nombre.length > 0 ? nombre : null;
}

Deno.serve(async (req: Request) => {
  const db = createClient(
    Deno.env.get("SUPABASE_URL")!,
    Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!,
  );

  // AUTORIZACION.
  //
  // verify_jwt ya obliga a presentar un JWT valido en el gateway, pero la
  // clave anon TAMBIEN es un JWT valido y es publica: esta en el frontend.
  // Sin esta segunda comprobacion cualquiera podria disparar un trabajo que
  // borra datos. El token vive en el Vault y se comprueba con una funcion que
  // devuelve si/no, de modo que el secreto nunca sale de la base de datos.
  const token = req.headers.get("x-retencion-token");
  const { data: autorizado, error: errAuth } = await db.rpc(
    "retencion_token_valido",
    { token },
  );

  if (errAuth || autorizado !== true) {
    return new Response(JSON.stringify({ error: "no autorizado" }), {
      status: 401,
      headers: { "Content-Type": "application/json" },
    });
  }

  const limite = new Date(Date.now() - dias * 86400_000).toISOString();

  let filasBorradas = 0;
  let fotosBorradas = 0;
  let huerfanasBorradas = 0;
  const errores: string[] = [];

  // ------------------------------------------------------------------
  // 1. Eventos caducados: foto primero, fila despues
  // ------------------------------------------------------------------
  for (let vuelta = 0; vuelta < MAX_LOTES; vuelta++) {
    const { data: filas, error } = await db
      .from("historial")
      .select("id, foto_url")
      .lt("timestamp", limite)
      .order("timestamp", { ascending: true })
      .limit(LOTE);

    if (error) {
      errores.push(`leyendo historial: ${error.message}`);
      break;
    }
    if (!filas || filas.length === 0) break;

    // Agrupar por nombre de foto: dos filas podrian apuntar al mismo objeto,
    // asi que se borra una vez y se retiran las dos.
    const porFoto = new Map<string, number[]>();
    const sinFoto: number[] = [];
    for (const fila of filas) {
      const nombre = nombreDeFoto(fila.foto_url);
      if (nombre === null) {
        sinFoto.push(fila.id);
      } else {
        porFoto.set(nombre, [...(porFoto.get(nombre) ?? []), fila.id]);
      }
    }

    // --- FOTO PRIMERO ---
    const idsABorrar = [...sinFoto];
    const nombres = [...porFoto.keys()];

    if (nombres.length > 0) {
      const { data: quitadas, error: errStorage } = await db.storage
        .from(BUCKET)
        .remove(nombres);

      if (errStorage) {
        // Las filas NO se tocan: manana se reintenta con el puntero intacto.
        errores.push(`borrando fotos: ${errStorage.message}`);
        break;
      }

      // remove() solo devuelve los objetos que existian. Que alguno no
      // estuviera (borrado a mano, o su subida fallo en su dia) no es un
      // problema: el objetivo es que no quede, y no queda. Su fila tambien se
      // va, porque si no se quedaria atascada para siempre.
      fotosBorradas += (quitadas ?? []).length;
      for (const ids of porFoto.values()) idsABorrar.push(...ids);
    }

    // --- FILA DESPUES ---
    if (idsABorrar.length > 0) {
      const { error: errFilas } = await db
        .from("historial")
        .delete()
        .in("id", idsABorrar);

      if (errFilas) {
        errores.push(`borrando filas: ${errFilas.message}`);
        break;
      }
      filasBorradas += idsABorrar.length;
    }

    if (filas.length < LOTE) break;
  }

  // ------------------------------------------------------------------
  // 2. Fotos huerfanas: objetos que ya no referencia ninguna fila
  // ------------------------------------------------------------------
  // La funcion SQL exige que el objeto sea mas viejo que la ventana de
  // retencion antes de considerarlo huerfano: el edge bufferea eventos cuando
  // pierde la red, asi que una foto puede llevar horas en el bucket antes de
  // que llegue su fila, y sin esa condicion se borraria la foto de un evento
  // que todavia esta esperando a subirse.
  const { data: huerfanas, error: errHuerfanas } = await db.rpc(
    "fotos_huerfanas",
    { dias_min: dias, limite_filas: LOTE * MAX_LOTES },
  );

  if (errHuerfanas) {
    errores.push(`buscando huerfanas: ${errHuerfanas.message}`);
  } else {
    const nombres = ((huerfanas ?? []) as { nombre: string }[])
      .map((h) => h.nombre)
      .filter((n) => n !== PREVIEW);

    for (let i = 0; i < nombres.length; i += LOTE) {
      const { data: quitadas, error } = await db.storage
        .from(BUCKET)
        .remove(nombres.slice(i, i + LOTE));
      if (error) {
        errores.push(`borrando huerfanas: ${error.message}`);
        break;
      }
      huerfanasBorradas += (quitadas ?? []).length;
    }
  }

  const resumen = {
    dias_retencion: dias,
    anteriores_a: limite,
    filas_borradas: filasBorradas,
    fotos_borradas: fotosBorradas,
    huerfanas_borradas: huerfanasBorradas,
    errores,
  };

  console.log("retencion:", JSON.stringify(resumen));

  return new Response(JSON.stringify(resumen), {
    status: errores.length > 0 ? 500 : 200,
    headers: { "Content-Type": "application/json" },
  });
});
