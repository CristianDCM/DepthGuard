"""
WebRTC Server para DepthGuard — Streaming de video en tiempo real.

Arquitectura de concurrencia:
  - FrameProvider: buffer thread-safe. El pipeline síncrono escribe frames aquí.
  - DepthGuardVideoTrack: track asíncrono de aiortc que lee de FrameProvider.
  - WebRTCManager: corre un bucle asyncio en un hilo daemon separado.
    Señalización vía Supabase Realtime Broadcast (canal por camera_id).

REGLA CRÍTICA: Este módulo NO importa ni modifica pipeline.py.
El pipeline.py llama a frame_provider.update_frame() como una función
normal y síncrona. Cero acoplamiento asíncrono en la dirección contraria.
"""

import asyncio
import threading
import time
import logging

import cv2
import numpy as np

try:
    import av
    from aiortc import RTCPeerConnection, RTCSessionDescription, RTCIceCandidate
    from aiortc.sdp import candidate_from_sdp
    from aiortc.contrib.media import MediaStreamTrack
    import fractions
    WEBRTC_DISPONIBLE = True
except ImportError:
    WEBRTC_DISPONIBLE = False
    logging.warning("⚠️  aiortc no instalado. WebRTC deshabilitado. Usando solo snapshots JPEG.")

from config.settings import TURN_URL, TURN_USERNAME, TURN_CREDENTIAL, SUPABASE_URL, SUPABASE_SERVICE_KEY

# ──────────────────────────────────────────────
# ICE Servers — STUN gratuito de Google + TURN Metered
# ──────────────────────────────────────────────

def _build_ice_servers():
    """Construye la lista de servidores ICE para RTCPeerConnection."""
    from aiortc import RTCIceServer
    servers = [
        RTCIceServer(urls=["stun:stun.l.google.com:19302", "stun:stun1.l.google.com:19302"]),
    ]
    if TURN_URL and TURN_USERNAME and TURN_CREDENTIAL:
        servers.append(RTCIceServer(
            urls=[TURN_URL, TURN_URL.replace(":80", ":443"), TURN_URL.replace("turn:", "turns:")],
            username=TURN_USERNAME,
            credential=TURN_CREDENTIAL,
        ))
        logging.info(f"✅ TURN server configurado: {TURN_URL}")
    else:
        logging.warning("⚠️  TURN no configurado. WebRTC puede fallar en redes con NAT simétrico.")
    return servers


# ──────────────────────────────────────────────
# FrameProvider — Puente sync → async
# ──────────────────────────────────────────────

class FrameProvider:
    """
    Buffer thread-safe que almacena el último frame del pipeline.

    El pipeline síncrono (hilo 1) escribe con update_frame().
    El VideoTrack asíncrono (hilo 5 / event loop) lee con get_frame().
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._frame: np.ndarray | None = None
        self._frame_count = 0

    def update_frame(self, frame_bgr: np.ndarray):
        """Llamado por el pipeline síncrono. Thread-safe."""
        with self._lock:
            self._frame = frame_bgr
            self._frame_count += 1

    def get_frame(self) -> tuple[np.ndarray | None, int]:
        """Retorna (frame_bgr, frame_count). Thread-safe."""
        with self._lock:
            return self._frame, self._frame_count


# ──────────────────────────────────────────────
# DepthGuardVideoTrack — VideoStreamTrack para aiortc
# ──────────────────────────────────────────────

if WEBRTC_DISPONIBLE:
    class DepthGuardVideoTrack(MediaStreamTrack):
        """
        Track de video que convierte frames OpenCV (BGR) al formato AV
        requerido por aiortc. Entrega ~30 FPS estables.

        Si no hay frame disponible (pipeline aún no entregó ninguno),
        entrega un frame negro para no bloquear la negociación WebRTC.
        """

        kind = "video"
        _TARGET_FPS = 30
        _FRAME_TIME = 1.0 / _TARGET_FPS

        def __init__(self, frame_provider: FrameProvider):
            super().__init__()
            self._provider = frame_provider
            self._pts = 0
            self._time_base = fractions.Fraction(1, 90000)  # estándar RTP
            self._last_frame_count = -1
            self._last_av_frame: "av.VideoFrame | None" = None
            self._frame_duration = int(90000 / self._TARGET_FPS)  # ticks por frame

        async def recv(self) -> "av.VideoFrame":
            """Llamado por aiortc en cada ciclo. Async puro."""
            # Respetar el ritmo de FPS objetivo
            await asyncio.sleep(self._FRAME_TIME)

            frame_bgr, frame_count = self._provider.get_frame()

            # Si hay un frame nuevo, convertirlo; si no, reusar el último
            if frame_bgr is not None and frame_count != self._last_frame_count:
                self._last_frame_count = frame_count
                frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
                av_frame = av.VideoFrame.from_ndarray(frame_rgb, format="rgb24")
                av_frame.pts = self._pts
                av_frame.time_base = self._time_base
                self._last_av_frame = av_frame
            elif self._last_av_frame is not None:
                # Reusar frame anterior con PTS actualizado
                self._last_av_frame = self._last_av_frame.reformat(
                    width=self._last_av_frame.width,
                    height=self._last_av_frame.height,
                )
                self._last_av_frame.pts = self._pts
            else:
                # Sin ningún frame todavía: entregar frame negro 640x480
                black = np.zeros((480, 640, 3), dtype=np.uint8)
                self._last_av_frame = av.VideoFrame.from_ndarray(black, format="rgb24")
                self._last_av_frame.pts = self._pts
                self._last_av_frame.time_base = self._time_base

            self._pts += self._frame_duration
            return self._last_av_frame


# ──────────────────────────────────────────────
# WebRTCManager — Orquestador de señalización y conexión
# ──────────────────────────────────────────────

class WebRTCManager:
    """
    Maneja el ciclo de vida WebRTC completo:
      - Corre un bucle asyncio en un hilo daemon separado.
      - Se suscribe a Supabase Realtime Broadcast para señalización.
      - Maneja múltiples conexiones concurrentes (un RTCPeerConnection por cliente).
      - Canal de señalización: webrtc-signaling-{camera_id} (aislado por cámara).
    """

    def __init__(self, frame_provider: "FrameProvider", camera_id: str):
        self._provider = frame_provider
        self._camera_id = camera_id
        self._canal_nombre = f"webrtc-signaling-{camera_id}"
        self._loop: asyncio.AbstractEventLoop | None = None
        self._conexiones: dict[str, "RTCPeerConnection"] = {}  # session_id → pc
        self._canal_supabase = None

    def iniciar(self):
        """
        Punto de entrada para el hilo daemon (Hilo 5).
        Crea el event loop asyncio y lo corre indefinidamente.
        """
        if not WEBRTC_DISPONIBLE:
            logging.warning("⚠️  WebRTCManager no iniciado: aiortc no disponible.")
            return

        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        try:
            self._loop.run_until_complete(self._run())
        except Exception as e:
            logging.error(f"❌ WebRTCManager error: {e}")
        finally:
            self._loop.close()

    async def _run(self):
        """Bucle principal asíncrono."""
        print(f"📡 WebRTC: iniciando en canal '{self._canal_nombre}'")
        await self._suscribir_supabase()

        # Mantener el event loop vivo indefinidamente
        while True:
            await asyncio.sleep(10)
            # Limpiar conexiones cerradas
            cerradas = [sid for sid, pc in self._conexiones.items()
                        if pc.connectionState in ("closed", "failed")]
            for sid in cerradas:
                del self._conexiones[sid]
                logging.info(f"🗑️  WebRTC: conexión {sid[:8]}... cerrada y eliminada")

    async def _suscribir_supabase(self):
        """
        Suscribe al canal Broadcast de Supabase para recibir
        ofertas SDP y candidatos ICE del frontend.
        """
        from supabase import create_async_client
        supabase = await create_async_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

        canal = supabase.channel(self._canal_nombre)

        def _on_mensaje(payload):
            """Callback síncrono de Supabase — puente a asyncio."""
            if self._loop is None:
                return
            evento = payload.get("payload", {})
            tipo = evento.get("tipo")
            session_id = evento.get("session_id", "default")
            sdp_len = len(evento.get("sdp", "")) if evento.get("sdp") else 0
            print(f"📩 WebRTC: tipo={tipo}, session={session_id[:12]}..., sdp={sdp_len} chars")

            if tipo == "offer":
                print(f"📥 WebRTC: offer recibida de sesión {session_id[:12]}")
                asyncio.run_coroutine_threadsafe(
                    self._manejar_offer(evento, canal, session_id),
                    self._loop,
                )
            elif tipo == "ice_candidate":
                asyncio.run_coroutine_threadsafe(
                    self._manejar_ice_candidate(evento, session_id),
                    self._loop,
                )

        canal.on_broadcast(event="signal", callback=_on_mensaje)
        await canal.subscribe()
        self._canal_supabase = canal
        print(f"✅ WebRTC: suscrito a Supabase Broadcast '{self._canal_nombre}'")

    async def _manejar_offer(self, evento: dict, canal, session_id: str):
        """Procesa una SDP offer del frontend y genera la answer."""
        from aiortc import RTCConfiguration

        sdp = evento.get("sdp")
        if not sdp:
            return

        # Guard contra offers duplicadas: si ya existe una conexión activa
        # para esta sesión, ignorar (previene re-renders de React).
        existing = self._conexiones.get(session_id)
        if existing and existing.connectionState not in ("closed", "failed"):
            logging.info(f"⏩ WebRTC: offer duplicada ignorada para {session_id[:8]}")
            return

        # Crear nueva conexión para esta sesión
        ice_servers = _build_ice_servers()
        pc = RTCPeerConnection(configuration=RTCConfiguration(iceServers=ice_servers))
        self._conexiones[session_id] = pc

        # Añadir track de video
        track = DepthGuardVideoTrack(self._provider)
        pc.addTrack(track)

        # NOTA: aiortc NO soporta Trickle ICE, así que @pc.on("icecandidate")
        # nunca se dispara. Los candidatos ICE van embebidos en el SDP de la answer
        # después de esperar a que ICE gathering termine.

        @pc.on("connectionstatechange")
        async def on_state():
            state = pc.connectionState
            logging.info(f"🔗 WebRTC [{session_id[:8]}]: estado → {state}")
            if state in ("failed", "closed"):
                await pc.close()
                self._conexiones.pop(session_id, None)

        # Procesar offer
        offer = RTCSessionDescription(sdp=sdp, type="offer")
        await pc.setRemoteDescription(offer)
        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)

        # Esperar a que ICE gathering termine para que el SDP
        # contenga todos los candidatos (máximo 10s)
        print(f"🧊 WebRTC: esperando ICE gathering para sesión {session_id[:8]}...")
        for _ in range(100):  # 100 × 0.1s = 10s timeout
            if pc.iceGatheringState == "complete":
                break
            await asyncio.sleep(0.1)

        if pc.iceGatheringState != "complete":
            print(f"⚠️  WebRTC: ICE gathering timeout para sesión {session_id[:8]}")
        else:
            print(f"🧊 WebRTC: ICE gathering completado para sesión {session_id[:8]}")

        # Enviar answer al frontend por Broadcast
        # El SDP ahora contiene todos los candidatos ICE embebidos
        await canal.send_broadcast(
            event="signal",
            data={
                "tipo": "answer",
                "session_id": session_id,
                "sdp": pc.localDescription.sdp,
            },
        )
        print(f"📤 WebRTC: answer enviada a sesión {session_id[:8]}...")

    async def _manejar_ice_candidate(self, evento: dict, session_id: str):
        """Agrega un candidato ICE del frontend a la conexión correspondiente."""
        pc = self._conexiones.get(session_id)
        if not pc:
            return
        try:
            candidate_data = evento.get("candidate", {})
            if candidate_data:
                candidate_sdp = candidate_data.get("candidate", "")
                if not candidate_sdp:
                    return
                # Parsear el string SDP a un objeto RTCIceCandidate de aiortc
                candidate = candidate_from_sdp(candidate_sdp)
                candidate.sdpMid = candidate_data.get("sdpMid")
                candidate.sdpMLineIndex = candidate_data.get("sdpMLineIndex")
                await pc.addIceCandidate(candidate)
        except Exception as e:
            logging.warning(f"⚠️  WebRTC: error añadiendo ICE candidate: {e}")

    # NOTA: _enviar_ice_candidate() fue eliminado.
    # aiortc no soporta Trickle ICE — los candidatos van embebidos en el SDP.
