"""Configuración desde variables de entorno (.env opcional)."""
import os
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from dotenv import load_dotenv

REQUERIDAS = ("BEDROCK_API_KEY", "BEDROCK_MODEL", "NVIDIA_API_KEY", "GOOGLE_API_KEY", "NIM_MODEL", "GEMINI_MODEL",
              "DATABASE_URL", "DATABASE_URL_RO")


class ConfigError(Exception):
    """Configuración ausente o inválida."""


@dataclass(frozen=True)
class Settings:
    bedrock_api_key: str
    bedrock_model: str
    nvidia_api_key: str
    google_api_key: str
    nim_model: str
    gemini_model: str
    database_url: str
    database_url_ro: str
    tasa_impuesto: Decimal = Decimal("0.16")
    nim_timeout: float = 20.0

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "Settings":
        sqlite = env.get("DATABASE_URL", "").strip().startswith("sqlite:")  # un solo archivo: no hay URL de solo lectura
        faltan = [k for k in REQUERIDAS if not env.get(k, "").strip() and not (sqlite and k == "DATABASE_URL_RO")]
        if faltan:
            raise ConfigError("Faltan variables de entorno: " + ", ".join(faltan))
        try:
            tasa = Decimal(env.get("TASA_IMPUESTO", "0.16"))
        except InvalidOperation:
            raise ConfigError("TASA_IMPUESTO no es un número válido") from None
        if not (Decimal(0) <= tasa < 1):
            raise ConfigError("TASA_IMPUESTO debe estar entre 0 y 1 (p. ej. 0.16)")
        try:
            timeout = float(env.get("NIM_TIMEOUT", "20"))
        except ValueError:
            raise ConfigError("NIM_TIMEOUT no es un número válido") from None
        return cls(
            bedrock_api_key=env["BEDROCK_API_KEY"].strip(),
            bedrock_model=env["BEDROCK_MODEL"].strip(),
            nvidia_api_key=env["NVIDIA_API_KEY"].strip(),
            google_api_key=env["GOOGLE_API_KEY"].strip(),
            nim_model=env["NIM_MODEL"].strip(),
            gemini_model=env["GEMINI_MODEL"].strip(),
            database_url=env["DATABASE_URL"].strip(),
            database_url_ro=env.get("DATABASE_URL_RO", "").strip() or env["DATABASE_URL"].strip(),
            tasa_impuesto=tasa,
            nim_timeout=timeout,
        )


def cargar() -> Settings:
    # Ruta explícita: load_dotenv() sin argumentos busca hacia arriba desde este archivo y heredaría
    # el .env de cualquier directorio padre (p. ej. claves de otros proyectos).
    load_dotenv(".env")
    return Settings.from_env(os.environ)
