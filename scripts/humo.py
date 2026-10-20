"""Prueba manual con LLMs reales (gasta tokens). Uso: uv run python scripts/humo.py

1) Bedrock como principal.  2) Bedrock con clave inválida para forzar el fallback a NIM.
Imprime el `model_name` crudo de cada proveedor: verifica que etiqueta_proveedor() los distinga."""
from dataclasses import replace

from rich.console import Console

from ventas.agent import construir_agente, herramientas_integradas
from ventas.cli.app import Sesion, ejecutar_turno
from ventas.config import cargar
from ventas.db import Db
from ventas.models import construir_modelos
from ventas.tools import construir_herramientas

PREGUNTA = "Hola, ¿qué agujas tienen y cuánto cuestan? Cotízame 10 de las de aluminio."


def correr(titulo, settings, db):
    console = Console()
    console.rule(titulo)
    herramientas = construir_herramientas(db, settings.tasa_impuesto)
    bedrock, nim, gemini = construir_modelos(settings)
    agente = construir_agente(bedrock, [nim, gemini], herramientas)
    propias = [h.name for h in herramientas]
    s = Sesion(agente=agente, db=db, console=console, bedrock_model=settings.bedrock_model, nim_model=settings.nim_model,
               gemini_model=settings.gemini_model, propias=propias,
               integradas=herramientas_integradas(agente, propias))
    ejecutar_turno(s, PREGUNTA)
    ultimo = agente.get_state(s.config).values["messages"][-1]
    console.print(f"proveedor={s.proveedor!r}  model_name crudo={ultimo.response_metadata.get('model_name')!r}")


if __name__ == "__main__":
    ajustes = cargar()
    db = Db(ajustes.database_url, ajustes.database_url_ro)
    try:
        correr("1) Bedrock principal", ajustes, db)
        correr("2) Bedrock caído -> fallback NIM", replace(ajustes, bedrock_api_key="invalida"), db)
    finally:
        db.close()
