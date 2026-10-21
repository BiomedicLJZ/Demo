"""Crea o actualiza un usuario del login web. Uso: uv run scripts/crear_usuario.py USUARIO EMPRESA [CLAVE]
Sin CLAVE la pide por teclado (no queda en el historial). AUTH_DB (por defecto auth.db) es el archivo de usuarios."""
import os
import sys
from getpass import getpass

from ventas.empresas import EMPRESAS
from ventas.usuarios import Usuarios

if len(sys.argv) not in (3, 4) or sys.argv[2] not in EMPRESAS:
    sys.exit(f"Uso: crear_usuario.py USUARIO EMPRESA [CLAVE]   (EMPRESA: {', '.join(EMPRESAS)})")
usuario, empresa = sys.argv[1], sys.argv[2]
clave = sys.argv[3] if len(sys.argv) == 4 else getpass("Clave: ")
try:
    Usuarios(os.environ.get("AUTH_DB", "auth.db")).guardar(usuario, clave, empresa)
except ValueError as e:
    sys.exit(str(e))
print(f"Usuario {usuario.strip().lower()!r} -> {EMPRESAS[empresa].nombre}")
