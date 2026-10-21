"""Usuarios del login web: contraseñas con scrypt y sesiones en memoria. Cada usuario pertenece a UNA empresa.

Viven en su propio archivo SQLite (AUTH_DB), nunca en la BD de una empresa: `consulta_sql` no debe poder leer los hashes.
"""
import hashlib
import hmac
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

SESION_SEGUNDOS = 12 * 3600
MIN_CLAVE = 8


def _hash(clave: str, sal: bytes) -> bytes:
    return hashlib.scrypt(clave.encode(), salt=sal, n=2**14, r=8, p=1)


class Usuarios:
    # shortcut: sesiones en memoria (se pierden al reiniciar) y sin límite de intentos de login; para varias réplicas
    # o internet hace falta un almacén compartido y rate limiting.
    def __init__(self, ruta):
        self.ruta = Path(ruta)
        self._sesiones: dict[str, tuple[str, str, float]] = {}  # token -> (usuario, empresa, vence)
        with self._con() as c:
            c.execute("CREATE TABLE IF NOT EXISTS usuarios (usuario TEXT PRIMARY KEY, sal BLOB NOT NULL, "
                      "hash BLOB NOT NULL, empresa TEXT NOT NULL)")

    @contextmanager
    def _con(self):
        c = sqlite3.connect(self.ruta)
        try:
            with c:  # commit al salir
                yield c
        finally:
            c.close()

    def guardar(self, usuario: str, clave: str, empresa: str) -> None:
        """Crea el usuario o le cambia la clave/empresa."""
        usuario = usuario.strip().lower()
        if not usuario or len(clave) < MIN_CLAVE:
            raise ValueError(f"Usuario vacío o clave de menos de {MIN_CLAVE} caracteres.")
        sal = secrets.token_bytes(16)
        with self._con() as c:
            c.execute("INSERT OR REPLACE INTO usuarios VALUES (?, ?, ?, ?)", (usuario, sal, _hash(clave, sal), empresa))

    def verificar(self, usuario: str, clave: str) -> tuple[str, str] | None:
        """(usuario, empresa) si las credenciales son válidas. Tarda lo mismo exista o no el usuario."""
        usuario = usuario.strip().lower()
        with self._con() as c:
            fila = c.execute("SELECT sal, hash, empresa FROM usuarios WHERE usuario = ?", (usuario,)).fetchone()
        sal, esperado, empresa = fila or (bytes(16), bytes(32), None)
        ok = hmac.compare_digest(_hash(clave, sal), esperado)
        return (usuario, empresa) if ok and fila else None

    def abrir_sesion(self, usuario: str, empresa: str) -> str:
        ahora = time.time()
        self._sesiones = {t: s for t, s in self._sesiones.items() if s[2] > ahora}
        token = secrets.token_urlsafe(32)
        self._sesiones[token] = (usuario, empresa, ahora + SESION_SEGUNDOS)
        return token

    def sesion(self, token: str) -> tuple[str, str] | None:
        s = self._sesiones.get(token)
        return (s[0], s[1]) if s and s[2] > time.time() else None

    def cerrar_sesion(self, token: str) -> None:
        self._sesiones.pop(token, None)
