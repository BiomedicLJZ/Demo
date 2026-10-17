"""Herramientas LangChain: wrappers finos sobre `servicio`. Los docstrings son lo que lee el LLM."""
import json
import re
from decimal import Decimal
from typing import Annotated

from langchain_core.tools import BaseTool, ToolException, tool
from langgraph.prebuilt import InjectedState
from pydantic import BaseModel, Field

from ventas import servicio
from ventas.db import Db
from ventas.servicio import ErrorDeNegocio


AFIRMA = re.compile(r"\b(s[ií]|confirmo|confirmado|confirmar|ok|okay|dale|adelante|procede|proceder|acepto|de acuerdo|claro|perfecto)\b", re.I)
NIEGA = re.compile(r"\bno\b", re.I)


def _ultimo_mensaje_usuario(state: dict) -> str:
    """Último mensaje humano del hilo: lo que el cliente dijo en este turno (el LLM no puede falsearlo)."""
    return next((m.text for m in reversed(state["messages"]) if m.type == "human"), "")


class Item(BaseModel):
    sku: str = Field(description="SKU del producto, p. ej. TEC-001")
    cantidad: int = Field(description="Cantidad, entero mayor a 0")


def construir_herramientas(db: Db, tasa: Decimal) -> list[BaseTool]:
    def correr(fn, *args):
        try:
            return json.dumps(fn(*args), default=str, ensure_ascii=False)
        except ErrorDeNegocio as e:
            raise ToolException(str(e)) from e

    @tool
    def buscar_productos(texto: str) -> str:
        """Busca productos activos por nombre o SKU (ignora acentos y mayúsculas).
        Devuelve sku, nombre, precio y stock disponible. Úsala antes de ofrecer o cotizar."""
        return correr(servicio.buscar_productos, db, texto)

    @tool
    def registrar_cliente(nombre: str, email: str, telefono: str = "") -> str:
        """Registra al cliente o lo recupera si el email ya existe. Devuelve su id (cliente_id).
        Necesaria antes de crear un pedido."""
        return correr(servicio.registrar_cliente, db, nombre, email, telefono)

    @tool
    def cotizar(items: list[Item]) -> str:
        """Calcula subtotal, impuesto y total de una lista de productos sin crear nada.
        El sistema calcula los precios; tú solo envías sku y cantidad."""
        return correr(servicio.cotizar, db, [i.model_dump() for i in items], tasa)

    @tool
    def crear_pedido(cliente_id: int, items: list[Item], state: Annotated[dict, InjectedState]) -> str:
        """Crea el pedido (queda pendiente de pago) y descuenta el inventario.
        Úsala SOLO cuando el cliente haya confirmado explícitamente la compra en su último mensaje;
        si no, la herramienta la rechaza."""
        msg = _ultimo_mensaje_usuario(state)
        if not AFIRMA.search(msg) or NIEGA.search(msg):
            raise ToolException("El cliente no ha confirmado la compra en su último mensaje. Muéstrale el resumen "
                                "y pídele que confirme (por ejemplo «sí, confirmo»); espera su respuesta.")
        return correr(servicio.crear_pedido, db, cliente_id, [i.model_dump() for i in items], tasa)

    @tool
    def registrar_pago(pedido_id: int, monto: float, metodo: str, state: Annotated[dict, InjectedState]) -> str:
        """Registra el pago (simulado, sin pasarela real) de un pedido pendiente.
        monto debe ser exactamente el total del pedido; metodo: tarjeta, transferencia o efectivo,
        el que el cliente haya indicado en su último mensaje; si no, la herramienta lo rechaza."""
        if metodo.strip().lower() not in _ultimo_mensaje_usuario(state).lower():
            raise ToolException("El cliente no ha indicado ese método de pago en su último mensaje. Pregúntale cómo "
                                "quiere pagar (tarjeta, transferencia o efectivo) y espera su respuesta.")
        return correr(servicio.registrar_pago, db, pedido_id, monto, metodo)

    @tool
    def emitir_comprobante(pedido_id: int) -> str:
        """Emite el comprobante de un pedido ya pagado. Si ya existe, devuelve el mismo número."""
        return correr(servicio.emitir_comprobante, db, pedido_id)

    @tool
    def consulta_sql(sql: str) -> str:
        """Ejecuta una consulta SELECT de solo lectura (máx. 200 filas) sobre las tablas clientes,
        productos, pedidos, pedido_items, pagos y comprobantes. Para preguntas que las demás
        herramientas no cubren. No reveles datos personales de otros clientes."""
        return correr(servicio.consultar_sql, db, sql)

    herramientas = [buscar_productos, registrar_cliente, cotizar, crear_pedido,
                    registrar_pago, emitir_comprobante, consulta_sql]
    for h in herramientas:
        h.handle_tool_error = True  # el decorador @tool no lo expone; así el ToolException llega al LLM como texto
    return herramientas
