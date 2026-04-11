"""Base de datos SQLite con WAL."""

import sqlite3
import json
import hashlib
import os
import threading
import datetime
from config.settings import DB_PATH, ADMIN_USUARIO, ADMIN_PASSWORD

_lock = threading.Lock()


def _hash_password(password, salt=None):
    """Genera hash seguro con PBKDF2-SHA256 + salt aleatorio."""
    if salt is None:
        salt = os.urandom(16)
    elif isinstance(salt, str):
        salt = bytes.fromhex(salt)

    hash_bytes = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, 100_000
    )
    return salt.hex() + ":" + hash_bytes.hex()


def _verificar_password(password, hash_almacenado):
    """Verifica un password contra su hash almacenado."""
    if ":" not in hash_almacenado:
        # Password legacy sin hash (plain text) — migrar
        return password == hash_almacenado

    salt_hex = hash_almacenado.split(":")[0]
    hash_esperado = _hash_password(password, salt_hex)
    return hash_esperado == hash_almacenado


class BaseDatos:

    def __init__(self):
        conn = self._conectar()
        c = conn.cursor()

        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=NORMAL")

        c.execute("""
            CREATE TABLE IF NOT EXISTS admin (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                usuario TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS usuarios_biometricos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT NOT NULL,
                embeddings_json TEXT NOT NULL,
                num_angulos INTEGER DEFAULT 1,
                fecha_registro TEXT NOT NULL
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS historial (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                estado TEXT NOT NULL,
                nombre TEXT,
                foto_ruta TEXT,
                confianza REAL DEFAULT 0,
                metricas_json TEXT,
                timestamp TEXT NOT NULL
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS suscripciones_push (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                suscripcion_json TEXT NOT NULL
            )
        """)

        # Admin por defecto
        try:
            c.execute(
                "INSERT INTO admin (usuario, password) VALUES (?, ?)",
                (ADMIN_USUARIO, _hash_password(ADMIN_PASSWORD))
            )
        except sqlite3.IntegrityError:
            pass

        conn.commit()
        conn.close()

    def _conectar(self):
        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    # === ADMIN ===
    def verificar_admin(self, usuario, password):
        conn = self._conectar()
        row = conn.execute(
            "SELECT * FROM admin WHERE usuario=?",
            (usuario,)
        ).fetchone()
        conn.close()

        if row is None:
            return None

        admin = dict(row)
        if _verificar_password(password, admin["password"]):
            # Migrar passwords legacy a hash si se detectan
            if ":" not in admin["password"]:
                self._migrar_password(usuario, password)
            return admin
        return None

    def _migrar_password(self, usuario, password):
        """Migra un password plain text a hash."""
        with _lock:
            conn = self._conectar()
            conn.execute(
                "UPDATE admin SET password=? WHERE usuario=?",
                (_hash_password(password), usuario)
            )
            conn.commit()
            conn.close()

    def crear_admin(self, usuario, password):
        with _lock:
            conn = self._conectar()
            conn.execute(
                "INSERT INTO admin (usuario, password) VALUES (?, ?)",
                (usuario, _hash_password(password))
            )
            conn.commit()
            conn.close()

    # === USUARIOS BIOMÉTRICOS ===
    def guardar_usuario(self, nombre, embeddings_lista):
        embeddings_json = json.dumps([e.tolist() for e in embeddings_lista])
        with _lock:
            conn = self._conectar()
            conn.execute(
                """INSERT INTO usuarios_biometricos
                   (nombre, embeddings_json, num_angulos, fecha_registro)
                   VALUES (?, ?, ?, ?)""",
                (nombre, embeddings_json, len(embeddings_lista),
                 datetime.datetime.now().isoformat())
            )
            conn.commit()
            conn.close()

    def obtener_todos_usuarios(self):
        conn = self._conectar()
        rows = conn.execute(
            "SELECT * FROM usuarios_biometricos"
        ).fetchall()
        conn.close()

        usuarios = []
        for row in rows:
            u = dict(row)
            u["embeddings"] = json.loads(u["embeddings_json"])
            del u["embeddings_json"]
            usuarios.append(u)

        return usuarios

    def obtener_usuarios_lista(self):
        conn = self._conectar()
        rows = conn.execute(
            "SELECT id, nombre, num_angulos, fecha_registro "
            "FROM usuarios_biometricos"
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def eliminar_usuario(self, usuario_id):
        with _lock:
            conn = self._conectar()
            conn.execute(
                "DELETE FROM usuarios_biometricos WHERE id=?",
                (usuario_id,)
            )
            conn.commit()
            conn.close()

    # === HISTORIAL ===
    def insertar_historial(self, estado, nombre, foto_ruta,
                           confianza, metricas):
        with _lock:
            conn = self._conectar()
            conn.execute(
                """INSERT INTO historial
                   (estado, nombre, foto_ruta, confianza,
                    metricas_json, timestamp)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (estado, nombre, foto_ruta, confianza,
                 json.dumps(metricas),
                 datetime.datetime.now().isoformat())
            )
            conn.commit()
            conn.close()

    def obtener_historial(self, limite=50):
        conn = self._conectar()
        rows = conn.execute(
            "SELECT * FROM historial ORDER BY id DESC LIMIT ?",
            (limite,)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    # === PUSH ===
    def guardar_suscripcion_push(self, suscripcion_json):
        with _lock:
            conn = self._conectar()
            conn.execute(
                "INSERT INTO suscripciones_push (suscripcion_json) VALUES (?)",
                (suscripcion_json,)
            )
            conn.commit()
            conn.close()

    def obtener_suscripciones_push(self):
        conn = self._conectar()
        rows = conn.execute(
            "SELECT suscripcion_json FROM suscripciones_push"
        ).fetchall()
        conn.close()
        return [json.loads(r["suscripcion_json"]) for r in rows]
