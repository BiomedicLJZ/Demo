"""Empresas (tenants). Cada una tiene su propia BD: el aislamiento es físico, no un filtro en las consultas."""
from dataclasses import dataclass

from ventas.config import Settings
from ventas.db import Db


@dataclass(frozen=True)
class Empresa:
    id: str
    nombre: str
    negocio: str  # va en el prompt del agente
    sugerencias: tuple[str, ...]
    db_url: str | None = None  # None = DATABASE_URL del .env (la empresa original)


# shortcut: rutas fijas relativas al directorio de trabajo; si hace falta moverlas, súbelas a Settings.
EMPRESAS = {e.id: e for e in (
    Empresa("agro", "Agroveterinaria",
            "una agroveterinaria (medicamentos, accesorios y productos para ganado y mascotas)",
            ("¿Qué agujas tienen?", "Quiero ver los shampoos", "Quiero hacer un pedido")),
    Empresa("fevasa", "Almacenadora Fevasa",
            "Almacenadora Fevasa, mayorista de granos, semillas, chiles secos, aceites y abarrotes en la Central de Abastos de Irapuato; "
            "se vende por kilo, bulto o caja",
            ("¿Qué aceites tienen?", "¿Cuánto cuesta el ajonjolí?", "Quiero hacer un pedido"),
            "sqlite:///fevasa.db"),
    Empresa("pastech", "Pastech de Occidente",
            "Pastech de Occidente, fabricante de pasta alimenticia en crudo (para botana: papa y trigo) vendida en piezas y cajas",
            ("¿Qué pastas de papa tienen?", "¿Cuánto cuesta el tapete de trigo?", "Quiero hacer un pedido"),
            "sqlite:///pastech.db"),
)}


def abrir_db(e: Empresa, s: Settings) -> Db:
    return Db(s.database_url, s.database_url_ro) if e.db_url is None else Db(e.db_url, e.db_url)
